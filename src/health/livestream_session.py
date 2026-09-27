"""Read-only Hermes session feed for the JIT Livestream panel (normal agent tasks, not benchmarks).

Source of truth is ~/.hermes/state.db (sessions + messages), opened read-only. The session id is the
same id used for the JIT overlay directory, so JIT telemetry joins on it without any extra mapping.
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

STATE_DB = Path(os.environ.get("HERMES_STATE_DB", Path.home() / ".hermes" / "state.db"))
LIVE_WINDOW_S = 600
FEED_LIMIT = 220
PREVIEW_CHARS = 420
PATH_KEYS = ("path", "file_path", "target_file")
WRITE_TOOLS = {"write_file", "patch", "save_patch", "street_write_file"}


@contextmanager
def _ro() -> Iterator[sqlite3.Connection]:
    # Closes on exit; a bare `with sqlite3.connect()` leaks the handle (EMFILE under polling).
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=1.0)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def _tool_name(raw: str | None) -> str:
    """Strip MCP namespacing so `mcp__srv__oven_terminal` and `terminal` read the same."""
    name = raw or "?"
    if name.startswith("mcp__"):
        name = name.split("__")[-1]
        name = name.split("_", 1)[1] if "_" in name and name.split("_", 1)[1] else name
    return name


def _summarize_args(name: str, raw: str) -> tuple[str, str | None]:
    """One-line human summary of tool arguments + the file path it touches (if any)."""
    try:
        args = json.loads(raw) if raw else {}
    except ValueError:
        return raw[:160], None
    if not isinstance(args, dict):
        return str(args)[:160], None
    path = next((str(args[k]) for k in PATH_KEYS if args.get(k)), None)
    for key in ("command", "query", "url", "image_url", "pattern", "goal", "code", "content"):
        if args.get(key):
            first = str(args[key]).strip().splitlines()[0] if str(args[key]).strip() else ""
            text = f"{path}  ·  {first}" if path and key != "content" else (path or first)
            return text[:220], path
    return (path or json.dumps(args, ensure_ascii=False))[:220], path


def list_sessions(hours: int = 24, limit: int = 30) -> list[dict[str, Any]]:
    if not STATE_DB.exists():
        return []
    since = time.time() - hours * 3600
    with _ro() as con:
        rows = con.execute(
            "SELECT id, source, model, title, cwd, started_at, ended_at, last_activity_at, message_count, tool_call_count "
            "FROM sessions WHERE COALESCE(last_activity_at, started_at) > ? AND COALESCE(hidden, 0) = 0 "
            "ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?", (since, limit)).fetchall()
    now = time.time()
    out = []
    for r in rows:
        last = r["last_activity_at"] or r["started_at"] or 0
        out.append({"id": r["id"], "source": r["source"], "model": r["model"], "title": r["title"] or "",
                    "project": Path(r["cwd"]).name if r["cwd"] else "", "messages": r["message_count"],
                    "tools": r["tool_call_count"], "last_activity": last,
                    "live": r["ended_at"] is None and now - last < LIVE_WINDOW_S})
    return out


def _feed_rows(con: sqlite3.Connection, session_id: str, after_id: int, limit: int) -> list[sqlite3.Row]:
    rows = con.execute(
        "SELECT id, role, content, tool_calls, tool_name, timestamp, token_count FROM messages "
        "WHERE session_id = ? AND id > ? ORDER BY id DESC LIMIT ?", (session_id, after_id, limit)).fetchall()
    return list(reversed(rows))


def feed_items(session_id: str, after_id: int = 0, limit: int = FEED_LIMIT) -> list[dict[str, Any]]:
    """Terminal-like event feed: user prompts, assistant text, tool calls and tool results."""
    if not STATE_DB.exists():
        return []
    with _ro() as con:
        rows = _feed_rows(con, session_id, after_id, limit)
    items: list[dict[str, Any]] = []
    for r in rows:
        content = r["content"] or ""
        if r["role"] == "user":
            items.append({"id": r["id"], "ts": r["timestamp"], "kind": "user", "text": _user_text(content)[:PREVIEW_CHARS]})
        elif r["role"] == "assistant":
            if content.strip():
                items.append({"id": r["id"], "ts": r["timestamp"], "kind": "say", "text": content.strip()[:PREVIEW_CHARS]})
            for call in _calls(r["tool_calls"]):
                fn = call.get("function", {})
                name = _tool_name(fn.get("name"))
                summary, _ = _summarize_args(name, fn.get("arguments", ""))
                items.append({"id": r["id"], "ts": r["timestamp"], "kind": "call", "tool": name, "text": summary})
        elif r["role"] == "tool":
            ok = not re.search(r'"(?:error|exit_code)":\s*(?:"[^"]+"|[1-9])', content[:600])
            items.append({"id": r["id"], "ts": r["timestamp"], "kind": "result", "tool": _tool_name(r["tool_name"]),
                          "chars": len(content), "ok": ok, "text": _result_preview(content)})
    return items


def _calls(raw: str | None) -> list[dict[str, Any]]:
    try:
        calls = json.loads(raw) if raw else []
    except ValueError:
        return []
    return calls if isinstance(calls, list) else []


def _user_text(content: str) -> str:
    """User prompts may carry injected context blocks / steering wrappers; keep the human part."""
    text = re.sub(r"<[a-zA-Z_-]+[^>]*>.*?</[a-zA-Z_-]+>", "", content, flags=re.S)
    text = re.sub(r"\[/?OUT-OF-BAND USER MESSAGE[^\]]*\]", "", text).strip()
    return text or content.strip()


def _result_preview(content: str) -> str:
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            body = data.get("output") or data.get("content") or data.get("analysis") or data.get("error")
            if body is None:  # structured result (write/patch): show its scalar fields
                body = "  ".join(f"{k}={v}" for k, v in data.items() if isinstance(v, (bool, int, float, str)) and len(str(v)) < 80)
            content = str(body)
    except ValueError:
        pass
    lines = [ln for ln in content.strip().splitlines() if ln.strip()]
    return " ⏎ ".join(lines[:3])[:260]


def session_state(session_id: str | None) -> dict[str, Any]:
    sessions = list_sessions()
    if not sessions:
        return {"available": False, "sessions": []}
    sid = session_id if any(s["id"] == session_id for s in sessions) else (
        next((s["id"] for s in sessions if s["live"]), sessions[0]["id"]))
    with _ro() as con:
        meta = con.execute(
            "SELECT id, source, model, title, cwd, git_branch, started_at, ended_at, last_activity_at, last_activity_description, "
            "message_count, tool_call_count, api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
            "reasoning_tokens, estimated_cost_usd FROM sessions WHERE id = ?", (sid,)).fetchone()
        rows = con.execute(
            "SELECT id, role, tool_calls, timestamp FROM messages WHERE session_id = ? AND role IN ('assistant','user') "
            "ORDER BY id DESC LIMIT 1500", (sid,)).fetchall()
    tools, files, timeline = Counter(), {}, []
    last_user = None
    for r in reversed(rows):
        if r["role"] == "user":
            timeline.append({"ts": r["timestamp"], "tool": "user"})
            last_user = r["id"]
            continue
        for call in _calls(r["tool_calls"]):
            fn = call.get("function", {})
            name = _tool_name(fn.get("name"))
            tools[name] += 1
            timeline.append({"ts": r["timestamp"], "tool": name})
            _, path = _summarize_args(name, fn.get("arguments", ""))
            if path:
                f = files.setdefault(path, {"path": path, "reads": 0, "writes": 0, "last": 0})
                f["writes" if name in WRITE_TOOLS else "reads"] += 1
                f["last"] = r["timestamp"]
    goal = ""
    if last_user:
        with _ro() as con:
            row = con.execute("SELECT content FROM messages WHERE id = ?", (last_user,)).fetchone()
        goal = _user_text(row["content"] or "")[:400] if row else ""
    m = dict(meta) if meta else {}
    now = time.time()
    last = m.get("last_activity_at") or m.get("started_at") or now
    return {
        "available": True, "id": sid, "meta": m, "goal": goal,
        "live": m.get("ended_at") is None and now - last < LIVE_WINDOW_S,
        "elapsed_s": round(now - (m.get("started_at") or now)), "idle_s": round(now - last),
        "tools": dict(tools.most_common(12)), "timeline": timeline[-600:],
        "files": sorted(files.values(), key=lambda f: f["last"], reverse=True)[:14],
        "sessions": sessions,
    }
