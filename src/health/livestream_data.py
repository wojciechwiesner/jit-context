"""Read-only data layer for the JIT Livestream panel.

Collects three evidence sources without mutating anything:
  1. Benchmark run (run.log + res.json) -> progress, per-task results, live cognition stage.
  2. JIT Context OS session telemetry (overlay SQLite) -> L0/L1/L2 latency, capsule vs haystack.
  3. Cognition memory (runner WAL db) + latest JEV scorer report.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ.get("JIT_STATE_DIR", HOME / ".hermes" / "state" / "ona-context"))
DEFAULT_RUN_ROOTS = [HOME / ".hermes" / "cache" / "scratch" / "cogab3", REPO / "benchmarks" / "results"]
GAIA_METADATA = Path("/tmp/gaia/validation_metadata.json")

STAGES = ["sensory", "plan", "ego", "tools", "guard", "sumienie", "rozwaga", "fidelity", "memory", "result"]

RE_START = re.compile(r"Starting .*? on (\d+) tasks \(Mode: (\w+), Worker: ([^)]+)\)")
RE_TASK = re.compile(r"COGNITIVE TASK \[(\d+)/(\d+)\]: (\w+)")
RE_TOOL = re.compile(r"\[Turn (\d+)\] Tool: (\w+)\(")
RE_GUARD = re.compile(r"\[Turn (\d+)\] Loop Guard: (\w+)")
RE_ROZWAGA = re.compile(r"\[Rozwaga\]: A='(.*?)' B='(.*?)' -> (\d) \((\w+)")
RE_GATE = re.compile(r"\[Sumienie Gate\]: (\w+) \(([^)]*)\)")
STAGE_MARKERS = [
    ("[Bus Intuition", "sensory"), ("[Bus Meta-Plan]", "plan"), ("[Ego Worker]", "ego"),
    ("] Tool: ", "tools"), ("Loop Guard:", "guard"), ("[Rozwaga]", "rozwaga"),
    ("[Fidelity Gate]", "fidelity"), ("[Sumienie Gate]", "sumienie"),
    ("[Experience Ingest]", "memory"), ("--> RESULT:", "result"),
]


def _roots() -> list[Path]:
    extra = os.environ.get("JIT_LIVESTREAM_ROOTS", "")
    return [Path(p).expanduser() for p in extra.split(":") if p] + DEFAULT_RUN_ROOTS


LIVE_WINDOW_S = 600  # a run/session counts as live if it wrote within the last 10 minutes


def _run_live(log: Path, mtime: float) -> bool:
    if time.time() - mtime > LIVE_WINDOW_S:
        return False
    with log.open("rb") as fh:
        fh.seek(max(0, log.stat().st_size - 200))
        return b"exit=" not in fh.read()


def list_runs() -> list[dict[str, Any]]:
    """Every directory holding a GAIA-style run.log, newest first; concurrent runs are flagged live."""
    runs = []
    for root in _roots():
        if not root.exists():
            continue
        for log in root.glob("*/run.log"):
            st = log.stat()
            runs.append({"id": log.parent.name, "path": str(log.parent), "mtime": st.st_mtime,
                         "size": st.st_size, "live": _run_live(log, st.st_mtime)})
    return sorted(runs, key=lambda r: r["mtime"], reverse=True)


def run_summary(run_dir: Path) -> dict[str, Any]:
    """Cheap per-run progress for the multi-run strip (no log parsing)."""
    try:
        res = json.loads((run_dir / "res.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = {}
    tasks = res.get("tasks", [])
    head = (run_dir / "run.log").open("r", encoding="utf-8", errors="replace").readline() if (run_dir / "run.log").exists() else ""
    m = RE_START.search(head)
    return {"done": len(tasks), "total": int(m.group(1)) if m else len(tasks), "worker": m.group(3) if m else "",
            "clean": sum(1 for t in tasks if t.get("is_clean_match")),
            "verified": sum(1 for t in tasks if t.get("is_verified_match"))}


def resolve_run(run_id: str | None) -> Path | None:
    runs = list_runs()
    if not runs:
        return None
    for r in runs:
        if run_id and r["id"] == run_id:
            return Path(r["path"])
    live = [r for r in runs if r["live"]]
    return Path((live or runs)[0]["path"])  # default: newest live run, else newest overall


def _gaia_levels() -> dict[str, dict[str, Any]]:
    try:
        rows = json.loads(GAIA_METADATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {r["task_id"]: {"level": str(r.get("Level")), "file": r.get("file_name") or ""} for r in rows}


def _planned_order(total: int, done_ids: list[str], levels: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Reconstruct the runner's task order (metadata order filtered by level) so pending tasks are visible.

    Picks the smallest level set whose first `total` tasks contain every finished task; falls back to
    the finished tasks only when the run used explicit --task_ids.
    """
    ordered = list(levels.items())
    for level_set in ({"1"}, {"1", "2"}, {"1", "2", "3"}):
        prefix = [(tid, m["level"]) for tid, m in ordered if m["level"] in level_set][:total]
        ids = {tid for tid, _ in prefix}
        if len(prefix) == total and all(d in ids for d in done_ids):
            return [{"id": tid, "level": lvl} for tid, lvl in prefix]
    return [{"id": d, "level": levels.get(d, {}).get("level", "?")} for d in done_ids]


@contextmanager
def _ro(db: Path) -> Iterator[sqlite3.Connection]:
    # `with sqlite3.connect(...)` only commits; it never closes, and the panel polls
    # every few seconds, so leaked handles hit EMFILE (Errno 24) within hours.
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def _parse_log(text: str) -> dict[str, Any]:
    head = RE_START.search(text)
    tools, guards, rozwaga_methods = Counter(), Counter(), Counter()
    rozwaga, api_errors, commits = [], 0, 0
    for line in text.splitlines():
        if m := RE_TOOL.search(line):
            tools[m.group(2)] += 1
        elif m := RE_GUARD.search(line):
            guards[m.group(2)] += 1
        elif m := RE_ROZWAGA.search(line):
            rozwaga_methods[m.group(4)] += 1
            rozwaga.append({"a": m.group(1)[:60], "b": m.group(2)[:60], "choice": int(m.group(3)), "method": m.group(4)})
        elif "API error" in line:
            api_errors += 1
        elif "[Experience Ingest]" in line:
            commits += 1
    blocks = list(RE_TASK.finditer(text))
    current = None
    if blocks:
        last = blocks[-1]
        body = text[last.end():]
        stage, turns, seen = "sensory", 0, []
        for line in body.splitlines():
            for marker, name in STAGE_MARKERS:
                if marker in line:
                    stage = name
                    if name not in seen:
                        seen.append(name)
            if m := RE_TOOL.search(line):
                turns = max(turns, int(m.group(1)))
        q = re.search(r"^Q: (.*)$", body, re.M)
        gt = re.search(r"^GT: (.*)$", body, re.M)
        gate = RE_GATE.search(body)
        current = {
            "index": int(last.group(1)), "total": int(last.group(2)), "task_id": last.group(3),
            "question": q.group(1) if q else "", "gt": gt.group(1) if gt else "",
            "stage": stage, "stages_seen": seen, "turns": turns,
            "gate": gate.group(1) if gate else None, "done": "--> RESULT:" in body,
        }
    return {
        "total": int(head.group(1)) if head else (int(blocks[-1].group(2)) if blocks else 0),
        "mode": head.group(2) if head else "", "worker": head.group(3) if head else "",
        "finished": "exit=" in text[-200:], "tools": dict(tools), "guards": dict(guards),
        "rozwaga": rozwaga[-12:], "rozwaga_methods": dict(rozwaga_methods),
        "api_errors": api_errors, "commits": commits, "current": current,
    }


def run_state(run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "run.log"
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    parsed = _parse_log(text)
    try:
        res = json.loads((run_dir / "res.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = {"tasks": []}
    levels = _gaia_levels()
    tasks, gates, reasons, durations = [], Counter(), Counter(), []
    for t in res.get("tasks", []):
        meta = levels.get(t["task_id"], {})
        verdict = "verified" if t.get("is_verified_match") else ("clean" if t.get("is_clean_match") else "fail")
        gates[t.get("gate_decision", "?")] += 1
        reasons[str(t.get("gate_reason", "")).split(":")[0]] += 1
        durations.append(float(t.get("duration_s") or 0))
        tasks.append({
            "id": t["task_id"], "level": meta.get("level", "?"), "file": bool(meta.get("file")),
            "verdict": verdict, "answer": str(t.get("model_answer", ""))[:120], "gt": str(t.get("ground_truth", ""))[:120],
            "gate": t.get("gate_decision"), "reason": t.get("gate_reason"), "duration": round(float(t.get("duration_s") or 0), 1),
            "tools": t.get("tools_count", 0), "forced": bool(t.get("forced_answer")),
            "rozwaga": bool(t.get("rozwaga")), "question": str(t.get("question", ""))[:220],
        })
    total = parsed["total"] or len(tasks)
    done = len(tasks)
    plan = _planned_order(total, [t["id"] for t in tasks], levels)
    per_level: dict[str, dict[str, int]] = {}
    for lvl in ("1", "2", "3"):
        planned = sum(1 for p in plan if p["level"] == lvl)
        rows = [t for t in tasks if t["level"] == lvl]
        per_level[lvl] = {"done": len(rows), "planned": planned,
                          "clean": sum(t["verdict"] != "fail" for t in rows), "verified": sum(t["verdict"] == "verified" for t in rows)}
    avg = sum(durations) / len(durations) if durations else 0.0
    st = log_path.stat() if log_path.exists() else None
    started = getattr(st, "st_birthtime", st.st_ctime) if st else time.time()  # ctime moves on every append on macOS
    return {
        "run_id": run_dir.name, "run_path": str(run_dir), "provenance": res.get("provenance", {}),
        "total": total, "done": done, "finished": parsed["finished"], "mode": parsed["mode"], "worker": parsed["worker"],
        "clean": sum(t["verdict"] != "fail" for t in tasks), "verified": sum(t["verdict"] == "verified" for t in tasks),
        "avg_s": round(avg, 1), "eta_s": round(avg * max(total - done, 0)), "elapsed_s": round(time.time() - started),
        "log_age_s": round(time.time() - log_path.stat().st_mtime, 1) if log_path.exists() else None,
        "per_level": per_level, "plan": plan, "gates": dict(gates), "reasons": dict(reasons), "tasks": tasks,
        "tools": parsed["tools"], "guards": parsed["guards"], "rozwaga": parsed["rozwaga"],
        "rozwaga_methods": parsed["rozwaga_methods"], "api_errors": parsed["api_errors"],
        "commits": parsed["commits"], "current": parsed["current"], "memory": memory_state(run_dir / "db.sqlite"),
    }


def memory_state(db: Path) -> dict[str, Any]:
    """Experience WAL written by the cognitive bus (Local Intuition Ingest)."""
    if not db.exists():
        return {"available": False}
    try:
        with _ro(db) as con:
            rows = con.execute("SELECT outcome, COUNT(*) n FROM experience_events GROUP BY outcome").fetchall()
            latest = con.execute(
                "SELECT intent, modalities, tool_sequence, outcome, created_at FROM experience_events ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
    except sqlite3.Error as exc:
        return {"available": False, "error": str(exc)}
    return {"available": True, "outcomes": {r["outcome"]: r["n"] for r in rows},
            "latest": [dict(r) for r in latest]}


def list_sessions(limit: int = 25) -> list[dict[str, Any]]:
    """Recent Hermes JIT session overlays that hold turn telemetry (fresh sessions start empty)."""
    candidates = list((STATE_DIR / "sessions").glob("*/*/overlay_*.db"))
    out = []
    for db in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            with _ro(db) as con:
                row = con.execute("SELECT COUNT(*), MAX(created_at), MAX(active_scope) FROM turn_telemetry").fetchone()
        except sqlite3.Error:
            continue
        if not row[0]:
            continue
        mtime = db.stat().st_mtime
        out.append({"id": db.parent.name, "scope": db.parent.parent.name, "path": str(db), "turns": row[0],
                    "last_turn": row[1], "active_scope": row[2], "mtime": mtime,
                    "live": time.time() - mtime < LIVE_WINDOW_S})
    return out


def _session_db(session_id: str | None, strict: bool = False) -> Path | None:
    """Overlay DB for a session id; `strict` disables the fallback to the latest session."""
    sessions = list_sessions()
    for s in sessions:
        if session_id and s["id"] == session_id:
            return Path(s["path"])
    if strict:
        return None
    return Path(sessions[0]["path"]) if sessions else None


def jit_state(session_id: str | None = None, limit: int = 48, strict: bool = False) -> dict[str, Any]:
    """L0/L1/L2 hot-path telemetry for one JIT session overlay (default: most recently active)."""
    db = _session_db(session_id, strict)
    if not db:
        return {"available": False}
    try:
        with _ro(db) as con:
            turns = con.execute(
                "SELECT created_at, active_scope, l2_triggered, l0_ms, l1_ms, l2_ms, hook_total_ms, capsule_tokens_est, "
                "haystack_tokens_est, jit_tokens_avoided_est, compression_ratio, degraded, invariants_failed_json "
                "FROM turn_telemetry ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            llm = con.execute(
                "SELECT started_at, requested_model, status, input_tokens, output_tokens, cache_read_tokens "
                "FROM llm_metrics ORDER BY id DESC LIMIT 60").fetchall()
            agg = con.execute(
                "SELECT COUNT(*) n, SUM(jit_tokens_avoided_est) avoided, AVG(l0_ms) l0, AVG(l1_ms) l1, AVG(l2_ms) l2, "
                "AVG(compression_ratio) cr, SUM(degraded) degraded FROM turn_telemetry").fetchone()
            overlay = con.execute("SELECT COUNT(*) FROM overlay WHERE status='active'").fetchone()[0]
    except sqlite3.Error as exc:
        return {"available": False, "error": str(exc), "db": str(db)}
    return {
        "available": True, "db": str(db), "session": db.parent.name,
        "db_age_s": round(time.time() - db.stat().st_mtime, 1), "overlay_active": overlay,
        "turns": [dict(r) for r in reversed(turns)], "llm": [dict(r) for r in reversed(llm)],
        "agg": {k: (round(agg[k], 2) if isinstance(agg[k], float) else agg[k]) for k in agg.keys()},
    }


def jev_state() -> dict[str, Any]:
    """Latest persisted JEV decision-scorer report (no live API call from the panel)."""
    reports = list((REPO / "benchmarks" / "results").glob("*/jev.json"))
    if not reports:
        return {"available": False}
    latest = max(reports, key=lambda p: p.stat().st_mtime)
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {"available": False, "error": str(exc)}
    data.pop("text", None)
    data.update({"available": True, "source": str(latest.relative_to(REPO)), "age_s": round(time.time() - latest.stat().st_mtime)})
    return data


def snapshot(run_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    runs = list_runs()[:20]
    run_dir = resolve_run(run_id)
    live_runs = [dict(r, **run_summary(Path(r["path"]))) for r in runs if r["live"]]
    sessions = list_sessions()
    from health import livestream_session  # local import: keeps benchmark mode usable without state.db
    try:
        hermes_sessions = livestream_session.list_sessions()
    except sqlite3.Error:
        hermes_sessions = []
    return {
        "generated_at": time.time(), "runs": runs, "live_runs": live_runs, "hermes_sessions": hermes_sessions,
        "sessions": [{k: s[k] for k in ("id", "scope", "turns", "last_turn", "active_scope", "live")} for s in sessions],
        "run": run_state(run_dir) if run_dir else None,
        "jit": jit_state(session_id), "jev": jev_state(), "stages": STAGES,
    }
