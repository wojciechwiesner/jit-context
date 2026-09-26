"""JIT Livestream panel server (official live view for Hermes sessions and benchmark runs).

Routes:
  GET /  |  /live?session=<id>  |  /?run=<id>   -> livestream.html (session mode by default)
  GET /static/<file>                            -> whitelisted panel assets
  GET /api/session?session=<id>                 -> Hermes session state + JIT telemetry for that session
  GET /api/session/stream?session=<id>          -> SSE feed of messages / tool calls from state.db
  GET /api/snapshot?run=<id>&session=<id>       -> benchmark run + cognition + JIT + JEV
  GET /api/stream?run=<id>                      -> SSE tail of the benchmark run.log
  GET /healthz                                  -> liveness probe for cmux Dock / launchd

Read-only by design: the panel never writes to run directories or telemetry databases.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from health import livestream_data, livestream_session

HERE = Path(__file__).parent
STATIC = {
    "livestream.css": "text/css; charset=utf-8",
    "livestream_common.js": "text/javascript; charset=utf-8",
    "livestream_session.js": "text/javascript; charset=utf-8",
    "livestream_bench.js": "text/javascript; charset=utf-8",
}
DEFAULT_PORT = int(os.environ.get("JIT_LIVESTREAM_PORT", "8766"))
BACKLOG_LINES = 400
POLL_S = 0.5


class Handler(BaseHTTPRequestHandler):
    server_version = "JITLivestream/1.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - keep launchd logs quiet
        return

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, fn) -> None:
        try:
            self._send(200, json.dumps(fn(), default=str).encode(), "application/json")
        except Exception as exc:  # surface the real error, never a fake payload
            self._send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        url = urlparse(self.path)
        query = parse_qs(url.query)
        run_id = (query.get("run") or [None])[0]
        session_id = (query.get("session") or [None])[0]
        path = url.path.rstrip("/") or "/"
        if path in ("/", "/index.html", "/live"):
            self._send(200, (HERE / "livestream.html").read_bytes(), "text/html; charset=utf-8")
        elif path.startswith("/static/") and path[8:] in STATIC:
            self._send(200, (HERE / path[8:]).read_bytes(), STATIC[path[8:]])
        elif path == "/healthz":
            self._send(200, b'{"ok":true}', "application/json")
        elif path == "/api/session":
            self._json(lambda: _session_payload(session_id))
        elif path == "/api/session/stream":
            self._session_stream(session_id)
        elif path == "/api/snapshot":
            self._json(lambda: livestream_data.snapshot(run_id, session_id))
        elif path == "/api/stream":
            self._run_stream(run_id)
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def _open_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def _emit(self, event: str, payload: dict) -> None:
        self.wfile.write(f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode())
        self.wfile.flush()

    def _ping(self, last: float) -> float:
        if time.time() - last > 15:
            self.wfile.write(b": ping\n\n")
            self.wfile.flush()
            return time.time()
        return last

    def _session_stream(self, session_id: str | None) -> None:
        state = livestream_session.session_state(session_id)
        if not state.get("available"):
            self._send(404, b'{"error":"no sessions"}', "application/json")
            return
        sid = state["id"]
        self._open_sse()
        try:
            items = livestream_session.feed_items(sid)
            self._emit("reset", {"session": sid, "items": items})
            last_id, last_ping = (items[-1]["id"] if items else 0), time.time()
            while True:
                time.sleep(1.0)
                new = livestream_session.feed_items(sid, after_id=last_id)
                if new:
                    last_id = new[-1]["id"]
                    self._emit("items", {"items": new})
                else:
                    last_ping = self._ping(last_ping)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _run_stream(self, run_id: str | None) -> None:
        run_dir = livestream_data.resolve_run(run_id)  # only known run dirs, no path input
        if run_dir is None:
            self._send(404, b'{"error":"no runs"}', "application/json")
            return
        log = run_dir / "run.log"
        self._open_sse()
        try:
            data = log.read_bytes() if log.exists() else b""
            backlog = data.decode("utf-8", "replace").splitlines()[-BACKLOG_LINES:]
            self._emit("reset", {"run": run_dir.name, "lines": backlog})
            offset, partial, last_ping = len(data), "", time.time()
            while True:
                time.sleep(POLL_S)
                size = log.stat().st_size if log.exists() else 0
                if size < offset:  # log rotated or rerun
                    offset, partial = 0, ""
                if size > offset:
                    with log.open("rb") as fh:
                        fh.seek(offset)
                        chunk = fh.read(size - offset)
                    offset = size
                    lines = (partial + chunk.decode("utf-8", "replace")).split("\n")
                    partial = lines.pop()
                    if lines:
                        self._emit("lines", {"lines": lines})
                else:
                    last_ping = self._ping(last_ping)
        except (BrokenPipeError, ConnectionResetError):
            return


def _session_payload(session_id: str | None) -> dict:
    state = livestream_session.session_state(session_id)
    sid = state.get("id")
    return {
        "generated_at": time.time(), "session": state,
        "jit": livestream_data.jit_state(sid, strict=True) if sid else {"available": False},
        "audit": _audit_payload(sid),
        "live_runs": [dict(r, **livestream_data.run_summary(Path(r["path"]))) for r in livestream_data.list_runs() if r["live"]],
    }


def _audit_payload(session_id: str | None, turns: int = 30) -> dict:
    """Per-turn autochecker reports for the session + the global jitjevmods backlog (read-only)."""
    from telemetry import jitjevmods
    reports = []
    path = jitjevmods.AUDIT_DIR / f"{session_id}.jsonl" if session_id else None
    if path and path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-turns:]
        for ln in lines:
            try:
                reports.append(json.loads(ln))
            except ValueError:
                continue
    mods = jitjevmods.ranked()
    return {"turns": reports, "mods": mods[:25], "open": sum(1 for m in mods if m.get("status") == "open"),
            "mods_path": str(jitjevmods.MODS_MD)}


def main() -> None:
    parser = argparse.ArgumentParser(description="JIT Livestream panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"JIT Livestream on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
