"""Per-turn autochecker for the Hermes JIT/JEV harness.

After every turn it compares the chain  project goal -> user prompt -> spec -> capsule -> output  and measures
how the harness behaved (tool errors, duplicate calls, re-reads, truncation re-fetches, turn length).
Findings are appended to audits/<session>.jsonl and merged into the jitjevmods.md improvement backlog.

Deterministic only: no LLM call, no network, read-only on state.db. Runs in a daemon thread from post_llm.
CLI backfill:  python -m telemetry.turn_audit --session <id> [--last N]
"""
from __future__ import annotations

import glob
import json
import re
import sqlite3
from contextlib import closing
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import SESSIONS_DIR
from telemetry.jitjevmods import AUDIT_DIR, record_mods
from telemetry.turn_audit_rules import SEVERITY_WEIGHT, check_alignment, check_harness, check_output

STATE_DB = Path.home() / ".hermes" / "state.db"
OOB = "[OUT-OF-BAND USER MESSAGE"
# Messages with role=user that are not a new human turn: steering, host notifications, reminders.
NOT_A_TURN_RE = re.compile(r"^\s*(\[OUT-OF-BAND USER MESSAGE|\[IMPORTANT:[^\]]{0,40}background process|\[SYSTEM:|<system-reminder>|\[ASYNC DELEGATION)", re.I)


def is_human_turn(msg: Dict[str, Any]) -> bool:
    return msg.get("role") == "user" and not NOT_A_TURN_RE.match(str(msg.get("content") or ""))
VERIFY_TOOLS = {"terminal", "execute_code", "browser_exec", "vision_analyze"}
WRITE_TOOLS = {"write_file", "patch"}
CODE_EXT = re.compile(r"\.(py|js|ts|tsx|jsx|html|css|sql|sh|toml|yaml|yml|json)$")
TRUNC = ("truncated by JIT context engine", "Output exceeded the capture window", "OUTPUT TRUNCATED")
CLAIM = re.compile(r"\b(działa|gotowe|zrobione|wdrożone|naprawione|works|passes|passed|fixed|deployed)\b", re.I)


# ---------------------------------------------------------------- normalisation
def tool_name(raw: Optional[str]) -> str:
    """`mcp__srv__oven_terminal` -> `terminal`, `save_patch` -> `patch`; native names pass through."""
    name = raw or "?"
    if name.startswith("mcp__"):
        name = name.split("__")[-1]
        head, _, tail = name.partition("_")
        name = tail or head
    return {"save_patch": "patch"}.get(name, name)


def strip_oob(text: str) -> str:
    return re.sub(r"\[/?OUT-OF-BAND USER MESSAGE[^\]]*\]", "", text or "").strip()


def _calls(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = msg.get("tool_calls")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return raw if isinstance(raw, list) else []


def turn_slice(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages of the last turn: everything after the last user message that is not out-of-band steering."""
    for i in range(len(messages) - 1, -1, -1):
        if is_human_turn(messages[i]):
            return messages[i:]
    return messages


def collect_tools(turn: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pair every tool call with its result (by tool_call_id, falling back to order)."""
    results = {m.get("tool_call_id"): str(m.get("content") or "") for m in turn if m.get("role") == "tool"}
    ordered = [str(m.get("content") or "") for m in turn if m.get("role") == "tool"]
    out: List[Dict[str, Any]] = []
    for m in turn:
        for c in _calls(m):
            fn = c.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"_raw": fn.get("arguments")}
            res = results.get(c.get("id")) or results.get(c.get("call_id"))
            if res is None:
                res = ordered[len(out)] if len(out) < len(ordered) else ""
            out.append({"name": tool_name(fn.get("name")), "args": args if isinstance(args, dict) else {}, "result": res})
    return out


def is_error(result: str) -> bool:
    head = result[:800]
    if re.search(r'"error":\s*"[^"]', head) or re.search(r'"exit_code":\s*[1-9]', head):
        return True
    return head.lstrip().startswith(("Error", "Traceback")) or '"success": false' in head


# ---------------------------------------------------------------- context sources
def session_files(session_id: str) -> Dict[str, Any]:
    """Newest capsule meta + overlay DB for a session; also reports if the session is split across scope dirs."""
    dirs = [Path(p) for p in glob.glob(str(SESSIONS_DIR / "*" / session_id)) if Path(p).is_dir()]
    metas = sorted((d / f"session_{session_id}.json" for d in dirs if (d / f"session_{session_id}.json").exists()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    dbs = sorted((d / f"overlay_{session_id}.db" for d in dirs if (d / f"overlay_{session_id}.db").exists()),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    meta: Dict[str, Any] = {}
    if metas:
        try:
            meta = json.loads(metas[0].read_text(encoding="utf-8"))
        except ValueError:
            meta = {}
    return {"meta": meta, "db": dbs[0] if dbs else None, "scope_dirs": sorted(d.parent.name for d in dirs)}


def session_cwd(session_id: str) -> Optional[str]:
    if not STATE_DB.exists():
        return None
    with closing(sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=1.0)) as con:
        row = con.execute("SELECT cwd FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row[0] if row and row[0] else None


def project_goal(cwd: Optional[str]) -> str:
    """First line under '## Active Goal' in <repo>/.planning/STATE.md (walks up to the git root)."""
    p = Path(cwd) if cwd else None
    while p and p != p.parent:
        state = p / ".planning" / "STATE.md"
        if state.exists():
            m = re.search(r"^##\s*(?:Active Goal|Goal|Cel)\s*\n+(.+)$", state.read_text(encoding="utf-8", errors="replace"), re.M)
            return m.group(1).strip() if m else ""
        if (p / ".git").exists():
            return ""
        p = p.parent
    return ""


def parse_capsule(capsule: str) -> Dict[str, Any]:
    def grab(label: str) -> str:
        m = re.search(rf"•\s*{label}:\s*(.+)", capsule or "")
        return m.group(1).strip() if m else ""
    scope = re.search(r'<ONA_CONTEXT[^>]*scope="([^"]*)"', capsule or "")
    targets = grab("Target Files").strip("[]")
    return {"goal": grab("Goal"), "spec": grab("Enhanced Technical Spec"), "criteria": grab("Acceptance Criteria"),
            "targets": [t.strip().strip("'\"") for t in targets.split(",") if t.strip()],
            "scope": scope.group(1) if scope else "", "project_line": grab("Project goal")}


def telemetry_row(db: Optional[Path], turn_id: Optional[str], since: float, until: float) -> Dict[str, Any]:
    if not db:
        return {}
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM turn_telemetry WHERE turn_id = ? ORDER BY id DESC LIMIT 1", (turn_id,)).fetchone() if turn_id else None
        if row is None:
            row = con.execute("SELECT * FROM turn_telemetry WHERE created_at BETWEEN ? AND ? ORDER BY id LIMIT 1",
                              (since - 5, until)).fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------- the audit
def audit(session_id: str, turn_id: str, prompt: str, output: str, tools: List[Dict[str, Any]],
          capsule: Optional[str], tele: Dict[str, Any], scope_dirs: List[str], cwd: Optional[str],
          duration_s: Optional[float]) -> Dict[str, Any]:
    """Pure function: inputs of one turn -> scored report. `capsule=None` means 'not retained' (backfill)."""
    goal = project_goal(cwd)
    cap = parse_capsule(capsule or "")
    findings = (check_alignment(prompt, capsule, cap, goal, tools, scope_dirs)
                + check_output(prompt, output, tools, VERIFY_TOOLS, CODE_EXT)
                + check_harness(tools, tele, duration_s, is_error, TRUNC))
    score = max(0, 100 - sum(SEVERITY_WEIGHT[f["severity"]] for f in findings))
    return {
        "ts": time.time(), "session": session_id, "turn": turn_id, "score": score,
        "chain": {"project_goal": goal[:200], "prompt": prompt[:300], "capsule_goal": cap["goal"][:200],
                  "spec": (cap["spec"] or cap["criteria"])[:200], "targets": cap["targets"][:5],
                  "output": (output or "")[:300], "capsule_retained": capsule is not None},
        "harness": {"tool_calls": len(tools), "errors": sum(1 for t in tools if is_error(t["result"])),
                    "tools": dict(Counter(t["name"] for t in tools).most_common(8)), "duration_s": round(duration_s or 0, 1),
                    "capsule_tokens": tele.get("capsule_tokens_est"), "hook_ms": tele.get("hook_total_ms")},
        "findings": [{k: f[k] for k in ("key", "severity", "title", "evidence")} for f in findings],
        "_full": findings,
    }


def persist(report: Dict[str, Any]) -> Path:
    full = report.pop("_full", [])
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '_', report['session'])}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    record_mods(full, {"session": report["session"], "turn": report["turn"][-12:]})
    return path


def audit_live_turn(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Entry point from the post_llm hook (Hermes passes the full conversation_history)."""
    session_id = str(ctx.get("session_id") or "")
    history = ctx.get("conversation_history") or []
    if not session_id or not history or session_id.startswith(("cron_", "subagent_", "test_", "bench_")):
        return None
    turn = turn_slice(history)
    prompt = strip_oob(str(ctx.get("user_message") or (turn[0].get("content") if turn else "") or ""))
    files = session_files(session_id)
    capsule = files["meta"].get("capsule", "")
    ts = [float(m["timestamp"]) for m in turn if isinstance(m.get("timestamp"), (int, float))]
    duration = (max(ts) - min(ts)) if len(ts) > 1 else None
    tele = telemetry_row(files["db"], files["meta"].get("turn_id"), min(ts) if ts else time.time() - 3600, time.time())
    report = audit(session_id, str(ctx.get("turn_id") or files["meta"].get("turn_id") or ""), prompt,
                   str(ctx.get("assistant_response") or ""), collect_tools(turn), capsule, tele,
                   files["scope_dirs"], session_cwd(session_id), duration)
    persist(report)
    return report


def backfill(session_id: str, last: int = 10) -> List[Dict[str, Any]]:
    """Audit the last N finished turns of a session from state.db (capsule text is not retained per turn)."""
    with closing(sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2.0)) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT id, role, content, tool_calls, tool_call_id, tool_name, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY id", (session_id,))]
        cwd_row = con.execute("SELECT cwd FROM sessions WHERE id = ?", (session_id,)).fetchone()
    starts = [i for i, m in enumerate(rows) if is_human_turn(m)]
    files = session_files(session_id)
    reports = []
    for a, b in zip(starts[-last - 1:], starts[-last:] + [len(rows)]):
        if a == b or b == len(rows) and a == starts[-1]:
            continue  # skip the turn still in progress
        turn = rows[a:b]
        finals = [m for m in turn if m["role"] == "assistant" and (m["content"] or "").strip()]
        ts = [float(m["timestamp"]) for m in turn if m["timestamp"]]
        tele = telemetry_row(files["db"], None, min(ts), max(ts)) if ts else {}
        report = audit(session_id, f"backfill:{turn[0]['id']}", strip_oob(turn[0]["content"] or ""),
                       finals[-1]["content"] if finals else "", collect_tools(turn), None, tele,
                       files["scope_dirs"], cwd_row[0] if cwd_row else None, (max(ts) - min(ts)) if len(ts) > 1 else None)
        persist(report)
        reports.append(report)
    return reports


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="JIT/JEV per-turn autochecker (backfill)")
    parser.add_argument("--session", required=True)
    parser.add_argument("--last", type=int, default=10)
    args = parser.parse_args()
    for r in backfill(args.session, args.last):
        print(f"{r['turn']:<22} score {r['score']:>3}  tools {r['harness']['tool_calls']:>3}  " + ", ".join(f["key"] for f in r["findings"]))


if __name__ == "__main__":
    main()
