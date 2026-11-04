#!/usr/bin/env python3
"""Loopback-only cockpit host and authenticated LLM proxy bridge; no filesystem writes API."""
import argparse
import hmac
import json
import signal
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 131072
CHAT_LOCK = threading.BoundedSemaphore(1)


class CockpitHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Do not log private conversation text or authentication headers.

    def allowed_origin(self):
        return self.headers.get("Origin") in (None, "null", self.server.origin)

    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}",
                                            f"localhost:{self.server.server_port}")

    def send_payload(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if self.allowed_origin() and self.headers.get("Origin"):
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self.valid_host() or not self.allowed_origin():
            return self.send_payload(403, {"error": "Origin or host rejected"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", self.server.origin))
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Cockpit-Token")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        if not self.valid_host() or not self.allowed_origin():
            return self.send_payload(403, {"error": "Origin or host rejected"})
        if self.path == "/health":
            return self.send_payload(200, {"status": "ok", "model": self.server.config["model"]})
        root = self.server.config["projects"].get(self.path.split("?", 1)[0])
        if root and self.headers.get("Origin") not in (None, self.server.origin):
            return self.send_payload(403, {"error": "Cross-origin project reads rejected"})
        if not root:
            return self.send_payload(404, {"error": "Unknown cockpit"})
        target = Path(root) / ".planning/state.html"
        if not target.is_file():
            return self.send_payload(404, {"error": "Generate the project cockpit first"})
        self.send_payload(200, target.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if not self.valid_host() or not self.allowed_origin():
            return self.send_payload(403, {"error": "Origin or host rejected"})
        if self.path != "/api/chat":
            return self.send_payload(404, {"error": "Unknown route"})
        token = self.headers.get("X-Cockpit-Token", "")
        if not hmac.compare_digest(token, self.server.config["token"]):
            return self.send_payload(401, {"error": "Invalid cockpit token; regenerate the page"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                return self.send_payload(413, {"error": "Request too large or empty"})
            payload = json.loads(self.rfile.read(length))
            messages = payload.get("messages")
            if not valid_messages(messages):
                return self.send_payload(400, {"error": "Invalid conversation"})
        except (ValueError, TypeError, AttributeError):
            return self.send_payload(400, {"error": "Invalid JSON"})
        if not CHAT_LOCK.acquire(blocking=False):
            return self.send_payload(429, {"error": "Lokalny model jest zajęty; spróbuj ponownie"})
        try:
            content = complete(self.server.config["model"], messages)
            self.send_payload(200, {"content": content})
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            self.send_payload(502, {"error": f"LLM proxy :8788: {type(error).__name__}; brak odpowiedzi dostawcy"})
        finally:
            CHAT_LOCK.release()


def valid_messages(messages):
    return (isinstance(messages, list) and 1 <= len(messages) <= 20
            and all(isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")
                    and isinstance(m.get("content"), str) and len(m["content"]) <= 50000
                    for m in messages))


def complete(model, messages):
    body = json.dumps({"model": model, "messages": messages, "stream": False,
                       "max_tokens": 900, "temperature": 0.2}).encode()
    request = urllib.request.Request("http://127.0.0.1:8788/v1/chat/completions", body,
                                     {"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as response:
        payload = json.load(response)
    content = payload["choices"][0]["message"]["content"].strip()
    if not content:
        raise ValueError("Empty model response")
    return content


def create_server(config, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), CockpitHandler)
    server.daemon_threads = True
    server.config = config
    server.origin = f"http://127.0.0.1:{server.server_port}"
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8778)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    server = create_server(config, args.port)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
