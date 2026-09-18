#!/usr/bin/env python3
"""JIT Context OS — Model Context Protocol (MCP) Server.

Exposes JIT Context OS capabilities to Claude Code, OpenCode, Cursor, and any
MCP-compatible coding agent over stdio JSON-RPC 2.0.

Endpoints/Tools:
- get_jit_context: Retrieve a live, lean (<1.5k tok) technical context capsule.
- record_jit_observation: Atomically write technical facts to shared L0 WAL.
- get_project_state: Fast access to .planning/STATE.md & DoD criteria without filesystem search.
- resolve_tool_capabilities: JIT recommendation of active vs dormant tool domains for a task.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

OBSERVATORY_URL = os.environ.get("JIT_OBSERVATORY_URL", "http://127.0.0.1:8765")
L0_DB_PATH = Path(
    os.path.expanduser(
        os.environ.get("JIT_L0_DB_PATH", "~/.hermes/state/ona-context/session_overlay.db")
    )
)


def _call_observatory_live_context(scope: str = "", task_intent: str = "") -> Optional[Dict[str, Any]]:
    """Query live Observatory endpoint on localhost:8765."""
    try:
        url = f"{OBSERVATORY_URL}/api/context/live"
        params = []
        if scope:
            params.append(f"scope={urllib.parse.quote(scope)}")
        if task_intent:
            params.append(f"intent={urllib.parse.quote(task_intent)}")
        if params:
            url += "?" + "&".join(params)

        req = urllib.request.Request(url, headers={"User-Agent": "JIT-Context-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def _fallback_l0_direct_read(scope: str = "") -> str:
    """Direct local fallback to SQLite WAL if Observatory HTTP daemon is down."""
    if not L0_DB_PATH.exists():
        return f"[JIT Context OS] Local overlay DB not found at {L0_DB_PATH}."

    try:
        conn = sqlite3.connect(f"file:{L0_DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()
        query = (
            "SELECT scope, key, value, updated_at FROM session_overlay "
            "ORDER BY updated_at DESC LIMIT 15"
        )
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "[JIT Context OS] Overlay DB active, no observations recorded yet."

        lines = ["<JIT_CONTEXT_FALLBACK source='sqlite_wal'>"]
        for r_scope, r_key, r_val, r_time in rows:
            if scope and r_scope != scope and r_scope != "general":
                continue
            lines.append(f"  • [{r_scope}] {r_key}: {r_val}")
        lines.append("</JIT_CONTEXT_FALLBACK>")
        return "\n".join(lines)
    except Exception as err:
        return f"[JIT Context OS] Error reading SQLite WAL: {err}"


def tool_get_jit_context(scope: str = "", task_intent: str = "") -> str:
    """Retrieve compiled JIT context capsule (<1.5k tokens)."""
    live = _call_observatory_live_context(scope=scope, task_intent=task_intent)
    if live and "capsule" in live:
        return live["capsule"]

    return _fallback_l0_direct_read(scope=scope)


def tool_record_jit_observation(fact: str, scope: str = "general", source: str = "agent") -> str:
    """Atomically record a verified technical observation to L0 WAL."""
    if not L0_DB_PATH.exists():
        L0_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(L0_DB_PATH))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_overlay (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                epistemic_weight REAL DEFAULT 1.0,
                source TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        import hashlib
        fact_key = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:12]
        cursor.execute(
            """
            INSERT INTO session_overlay (session_id, scope, key, value, epistemic_weight, source)
            VALUES (?, ?, ?, ?, 1.0, ?)
            """,
            ("mcp_agent_session", scope, f"obs_{fact_key}", fact, source),
        )
        conn.commit()
        conn.close()
        return f"Recorded observation under scope '{scope}' [key: obs_{fact_key}]."
    except Exception as err:
        return f"Failed to record observation: {err}"


def tool_get_project_state(project_path: str = ".") -> str:
    """Read .planning/STATE.md and DoD criteria without scanning entire directory tree."""
    p = Path(project_path).resolve()
    state_file = p / ".planning" / "STATE.md"
    if not state_file.exists():
        # Try current working directory
        state_file = Path.cwd() / ".planning" / "STATE.md"

    if state_file.exists():
        try:
            content = state_file.read_text(encoding="utf-8")
            return content[:4000]
        except Exception as err:
            return f"Error reading STATE.md: {err}"

    return f"No .planning/STATE.md found at {p}. Use 'jit init' to initialize project tracking."


def tool_resolve_tool_capabilities(task_description: str) -> str:
    """Suggest active tool domain vs dormant domains for a task."""
    desc = task_description.lower()
    active = ["core.code"]
    if any(w in desc for w in ["browser", "web", "dom", "click", "ui", "scrape", "screenshot"]):
        active.append("web.browser")
    if any(w in desc for w in ["search", "google", "find on web", "docs", "lookup"]):
        active.append("web.search")
    if any(w in desc for w in ["db", "database", "sql", "postgres", "sqlite", "query"]):
        active.append("database")
    if any(w in desc for w in ["git", "commit", "branch", "pr", "diff"]):
        active.append("git")

    return json.dumps({
        "recommended_active_domains": active,
        "dormant_domains": [d for d in ["web.browser", "web.search", "database", "git", "kanban", "multimedia"] if d not in active],
        "guidance": "Hydrate only active domains to prevent context bloat."
    }, indent=2)


TOOLS = [
    {
        "name": "get_jit_context",
        "description": "Get a lean (<1.5k tokens) JIT technical context capsule for the current scope and project without blowing up the context window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "Project scope (e.g. boocco, wynajmujemy, hermes)"},
                "task_intent": {"type": "string", "description": "Optional task intent or prompt for dynamic relevance scoring"}
            }
        }
    },
    {
        "name": "record_jit_observation",
        "description": "Atomically record a verified technical observation or requirement to the shared L0 SQLite WAL memory for all agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The exact technical fact or rule discovered"},
                "scope": {"type": "string", "description": "Target project scope"},
                "source": {"type": "string", "description": "Source identifier (e.g. claude-code, opencode)"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "get_project_state",
        "description": "Fast deterministic retrieval of .planning/STATE.md and DoD criteria without expensive repository tree searches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to project root directory"}
            }
        }
    },
    {
        "name": "resolve_tool_capabilities",
        "description": "Determine which tool capability domains should be hydrated vs kept dormant for a given task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Description of the task to evaluate"}
            },
            "required": ["task_description"]
        }
    }
]


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "jit-context-mcp",
                    "version": "0.3.0"
                }
            }
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        }
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        result_text = ""
        if tool_name == "get_jit_context":
            result_text = tool_get_jit_context(scope=args.get("scope", ""), task_intent=args.get("task_intent", ""))
        elif tool_name == "record_jit_observation":
            result_text = tool_record_jit_observation(fact=args.get("fact", ""), scope=args.get("scope", "general"), source=args.get("source", "agent"))
        elif tool_name == "get_project_state":
            result_text = tool_get_project_state(project_path=args.get("project_path", "."))
        elif tool_name == "resolve_tool_capabilities":
            result_text = tool_resolve_tool_capabilities(task_description=args.get("task_description", ""))
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}]
            }
        }
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            res = handle_request(req)
            if res is not None:
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
        except Exception as err:
            err_res = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {err}"}
            }
            sys.stdout.write(json.dumps(err_res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
