"""Controlled A/B of the JIT Claude Code hooks: `claude -p` with JIT on vs off in throwaway git worktrees.

Generalises benchmarks/run_jit_ab_opus55.py (Hermes, faktury) to any registered project and to Claude Code:
- every call gets a fresh detached worktree of the project at one fixed commit; worktrees live in a sibling
  dir `<repo>-jitbench-<batch>` so JIT scope resolution maps them to the main repo (l1/scope.py),
- JIT off = JIT_OFF_ENV. The Claude Code hooks honour JIT_CLAUDE_HOOK / JIT_SPILL_HOOK / JIT_COMPACT_HOOK;
  JIT_DISABLE is read by nothing and ONA_CONTEXT_MODE loses to mode.json in hooks.py, so neither is used,
- read-only built-in tools only, no MCP servers (strict empty MCP config), no session persistence (bench calls
  do not show up in `jit hub usage`), the arm order alternates per run to balance prompt-cache warmup,
- usage, turns and cost come from `--output-format json`; wall time is measured here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from hub import bench_store
from hub.bench_tasks import BenchTask

CLAUDE_BIN = "claude"
READ_ONLY_TOOLS = "Read,Grep,Glob"
JIT_OFF_ENV = {"JIT_CLAUDE_HOOK": "0", "JIT_SPILL_HOOK": "0", "JIT_COMPACT_HOOK": "0"}
CALLS_PER_TASK_RUN = len(bench_store.ARMS)
CALL_TIMEOUT_SECONDS = 900
GIT_TIMEOUT_SECONDS = 60
MAX_ANSWER_CHARS = 4000
MAX_ERROR_CHARS = 500
WORK_DIR_INFIX = "-jitbench-"


class BenchError(RuntimeError):
    """The batch cannot continue (git worktree failure, missing claude)."""


@dataclass(frozen=True)
class BenchSpec:
    project: str
    repo: Path
    tasks: Sequence[BenchTask]
    runs: int
    model: str


def estimated_calls(task_count: int, runs: int) -> int:
    return task_count * runs * CALLS_PER_TASK_RUN


def arm_order(run_index: int) -> tuple:
    """Run 0: on, off; run 1: off, on; ... so neither arm always gets the warm prompt cache."""
    return bench_store.ARMS if run_index % 2 == 0 else tuple(reversed(bench_store.ARMS))


def claude_command(prompt: str, model: str) -> List[str]:
    return [
        CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--model", model,
        "--tools", READ_ONLY_TOOLS, "--allowedTools", READ_ONLY_TOOLS,
        "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}', "--no-session-persistence",
    ]


def arm_env(arm: str, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for one arm: off sets every hook switch to 0, on removes them all."""
    env = {key: value for key, value in (base if base is not None else os.environ).items() if key not in JIT_OFF_ENV}
    if arm == bench_store.ARM_OFF:
        env.update(JIT_OFF_ENV)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=GIT_TIMEOUT_SECONDS)


def head_commit(repo: Path) -> str:
    res = _git(repo, "rev-parse", "HEAD")
    if res.returncode != 0:
        raise BenchError(f"git rev-parse HEAD: {res.stderr.strip()}")
    return res.stdout.strip()


def add_worktree(repo: Path, path: Path, commit: str) -> None:
    res = _git(repo, "worktree", "add", "--detach", str(path), commit)
    if res.returncode != 0:
        raise BenchError(f"git worktree add {path}: {res.stderr.strip()}")


def remove_worktree(repo: Path, path: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(path))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    _git(repo, "worktree", "prune")


def _parse_json(stdout: str) -> Optional[dict]:
    """The single result object; tolerates log lines before it."""
    text = stdout.strip()
    candidates = [text] + [line for line in reversed(text.splitlines()) if line.startswith("{")]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def result_fields(data: Optional[dict]) -> Dict[str, object]:
    """ab_runs columns from the CLI JSON; absent values stay None."""
    if data is None:
        return {"is_error": 1, "error": "brak wyniku JSON od claude"}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    is_error = bool(data.get("is_error")) or data.get("subtype") not in (None, "success")
    answer = data.get("result")
    return {
        "is_error": int(is_error),
        "error": str(data.get("subtype") or answer or "")[:MAX_ERROR_CHARS] if is_error else None,
        "num_turns": data.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "cost_usd": data.get("total_cost_usd"),
        "duration_api_ms": data.get("duration_api_ms"),
        "session_id": data.get("session_id"),
        "answer": answer[:MAX_ANSWER_CHARS] if isinstance(answer, str) else None,
    }


def _invoke(command: List[str], cwd: Path, env: Dict[str, str]) -> Dict[str, object]:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True,
                              timeout=CALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"wall_s": round(time.monotonic() - started, 3), "exit_code": None, "is_error": 1,
                "error": f"timeout po {CALL_TIMEOUT_SECONDS} s"}
    except OSError as exc:
        raise BenchError(f"nie można uruchomić {command[0]}: {exc}") from exc
    data = _parse_json(proc.stdout)
    fields = result_fields(data)
    fields.update(wall_s=round(time.monotonic() - started, 3), exit_code=proc.returncode)
    if proc.returncode != 0:
        fields["is_error"] = 1
        if data is None or not fields.get("error"):
            fields["error"] = proc.stderr.strip()[-MAX_ERROR_CHARS:] or f"exit {proc.returncode}"
    return fields


def run_call(spec: BenchSpec, task: BenchTask, run_index: int, arm: str, work_root: Path,
             commit: str) -> Dict[str, object]:
    """One `claude -p` call in its own worktree; returns the ab_runs row (not yet stored)."""
    worktree = work_root / f"{task.task_id}-r{run_index}-{arm}"
    add_worktree(spec.repo, worktree, commit)
    row: Dict[str, object] = {
        "project": spec.project, "repo_path": str(spec.repo), "head": commit, "task_id": task.task_id,
        "prompt": task.prompt, "run_index": run_index, "arm": arm, "model": spec.model,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        row.update(_invoke(claude_command(task.prompt, spec.model), worktree, arm_env(arm)))
    finally:
        remove_worktree(spec.repo, worktree)
    return row


def new_batch_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{os.urandom(2).hex()}"


def run_batch(spec: BenchSpec, conn, progress: Callable[[dict], None] = lambda row: None) -> str:
    """Run every (run, task, arm) call, storing each row as soon as it finishes. Returns the batch id."""
    batch_id = new_batch_id()
    commit = head_commit(spec.repo)
    work_root = spec.repo.parent / f"{spec.repo.name}{WORK_DIR_INFIX}{batch_id}"
    work_root.mkdir(parents=True)
    try:
        for run_index in range(spec.runs):
            for task in spec.tasks:
                for arm in arm_order(run_index):
                    row = run_call(spec, task, run_index, arm, work_root, commit)
                    row["batch_id"] = batch_id
                    bench_store.insert_run(conn, row)
                    progress(row)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
        _git(spec.repo, "worktree", "prune")
    return batch_id
