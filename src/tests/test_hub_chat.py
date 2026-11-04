"""Hub project chat: real HTTP through the Mission Control handler against a fake OpenAI-compatible upstream."""

import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import chat_history, chat_prompt, chat_upstream, registry
from hub import stats as hub_stats

STATE_MARKER = "MARKER-STATE-H15 hub chat backend in progress"
DOSSIER_MARKER = "MARKER-DOSSIER project card"
FAKE_REPLY = "Odpowiedź modelu testowego."
SLOW_SECONDS = 2.0


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"path": self.path, "body": body})
        mode = self.server.mode
        if mode == "slow":
            time.sleep(SLOW_SECONDS)
        if mode == "error":
            payload, code = b'{"error":"provider exploded"}', 500
        else:
            payload, code = json.dumps({"model": body["model"], "usage": {"total_tokens": 42},
                                        "choices": [{"message": {"content": FAKE_REPLY}}]}).encode(), 200
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass  # the client already gave up (timeout case)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


def make_repo(path: Path, state_text: str) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text(state_text, encoding="utf-8")
    (path / ".planning" / "ARCHITECTURE.mmd").write_text("graph TD\n  hub --> chat\n", encoding="utf-8")
    (path / "README.md").write_text("# Demo\n\nQuickstart: run it.\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "first"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(config.HUB_DIR_ENV, str(tmp_path / "hub"))
    monkeypatch.delenv(hub_routes.ORIGINS_ENV, raising=False)
    monkeypatch.delenv(chat_upstream.API_KEY_ENV, raising=False)
    vault = tmp_path / "vault" / "projects"
    vault.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECTS_DIR", vault)
    repo = make_repo(tmp_path / "demo", f"# State\n\n**Projekt:** demo\n\n## Tasks\n- [ ] {STATE_MARKER}\n")
    (vault / "demo.md").write_text(f"# Demo\n{DOSSIER_MARKER}\n", encoding="utf-8")
    entry, _ = registry.register_project(repo)
    stats_file = hub_stats.stats_path(entry["slug"])
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    stats_file.write_text(json.dumps({"generated_at": "2026-11-04T10:00:00", "usage": {"days": [], "totals": {}},
                                      "suggestions": {"suggestions": [{"id": "stale-state", "severity": "high",
                                                                       "summary": "STATE.md stary"}]}}),
                          encoding="utf-8")
    upstream = serve(FakeUpstream)
    upstream.requests, upstream.mode = [], "ok"
    monkeypatch.setenv(chat_upstream.URL_ENV, f"http://127.0.0.1:{upstream.server_address[1]}/v1")
    monkeypatch.setenv(chat_upstream.MODEL_ENV, "test-model")
    hub = serve(livestream.Handler)
    base = f"http://127.0.0.1:{hub.server_address[1]}"
    yield {"base": base, "slug": entry["slug"], "entry": entry, "repo": repo, "upstream": upstream}
    for server in (hub, upstream):
        server.shutdown()
        server.server_close()


def call(env, payload, token=None, method="POST"):
    headers = {"Origin": env["base"], hub_routes.CSRF_HEADER: token or hub_routes.csrf_token(),
               "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if method == "POST" else None
    url = env["base"] + hub_routes.CHAT_ROUTE + ("" if method == "POST" else f"?slug={env['slug']}")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def ask(env, text="Jaki jest status?"):
    return call(env, {"slug": env["slug"], "messages": [{"role": "user", "content": text}]})


def test_success_sends_grounded_prompt_and_stores_history(env):
    status, body = ask(env)
    assert status == 200 and body["reply"] == FAKE_REPLY and body["model"] == "test-model"
    sent = env["upstream"].requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["body"]["model"] == "test-model"
    system, user = sent["body"]["messages"]
    assert system["role"] == "system" and user == {"role": "user", "content": "Jaki jest status?"}
    prompt = system["content"]
    assert len(prompt) <= chat_prompt.MAX_PROMPT_CHARS and body["prompt_chars"] == len(prompt)
    assert STATE_MARKER in prompt and DOSSIER_MARKER in prompt and "stale-state" in prompt
    assert "Źródła w tym prompcie:" in prompt and "- STATE.md (" in prompt and "- ROADMAP.md: brak: brak pliku" in prompt
    by_name = {source["name"]: source for source in body["sources"]}
    assert by_name["STATE.md"]["status"] == "included" and by_name["ROADMAP.md"]["status"] == "missing"
    assert all("text" not in source for source in body["sources"])
    status, history = call(env, None, method="GET")
    roles = [record["role"] for record in history["messages"]]
    assert status == 200 and roles == ["user", "assistant"] and history["messages"][1]["content"] == FAKE_REPLY


def test_upstream_500_is_an_explicit_error_not_an_answer(env):
    env["upstream"].mode = "error"
    status, body = ask(env)
    assert status == 502 and body["upstream_status"] == 500 and "reply" not in body
    assert "HTTP 500" in body["error"] and "provider exploded" in body["error"] and body["sources"]
    records = chat_history.load(env["slug"])["messages"]
    assert [r["role"] for r in records] == ["user", "error"] and records[1]["upstream_status"] == 500


def test_upstream_timeout_returns_504(env, monkeypatch):
    monkeypatch.setenv(chat_upstream.TIMEOUT_ENV, "0.3")
    env["upstream"].mode = "slow"
    started = time.monotonic()
    status, body = ask(env)
    assert status == 504 and body["upstream_status"] is None and "brak odpowiedzi w 0.3 s" in body["error"]
    assert time.monotonic() - started < SLOW_SECONDS and "reply" not in body


def test_refused_connection_is_502(env, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    monkeypatch.setenv(chat_upstream.URL_ENV, f"http://127.0.0.1:{free_port}/v1")
    status, body = ask(env)
    assert status == 502 and body["upstream_status"] is None and "połączenie nieudane" in body["error"]


@pytest.mark.parametrize("payload, code", [
    ({"messages": [{"role": "user", "content": "x"}]}, 400),
    ({"slug": "SLUG", "messages": [{"role": "system", "content": "x"}]}, 400),
    ({"slug": "SLUG", "messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]}, 400),
    ({"slug": "SLUG", "messages": []}, 400),
    ({"slug": "nope", "messages": [{"role": "user", "content": "x"}]}, 404),
])
def test_bad_requests(env, payload, code):
    payload = json.loads(json.dumps(payload).replace("SLUG", env["slug"]))
    status, body = call(env, payload)
    assert status == code and body["error"] and not env["upstream"].requests


def test_chat_post_needs_csrf_token(env):
    status, _ = call(env, {"slug": env["slug"], "messages": [{"role": "user", "content": "x"}]}, token="wrong")
    assert status == 403 and not env["upstream"].requests


def test_prompt_is_capped_and_lists_truncation(env):
    state = env["repo"] / ".planning" / "STATE.md"
    state.write_text(STATE_MARKER + "\n" + "x" * 100000, encoding="utf-8")
    (env["repo"] / "ROADMAP.md").write_text("roadmap " * 5000, encoding="utf-8")
    prompt, sources = chat_prompt.build_system_prompt(env["entry"])
    by_name = {source["name"]: source for source in sources}
    assert len(prompt) <= chat_prompt.MAX_PROMPT_CHARS and STATE_MARKER in prompt
    assert by_name["STATE.md"]["truncated"] and by_name["ROADMAP.md"]["truncated"]
    assert "znaków, obcięte" in prompt and "[... obcięto" in prompt


def test_unreadable_dossier_is_reported(env, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", env["repo"] / "no-vault")
    _, sources = chat_prompt.build_system_prompt(env["entry"])
    dossier = sources[0]
    assert dossier["status"] == "missing" and "brak pliku" in dossier["reason"] and "Projekt" in dossier["reason"]


def test_settings_precedence(env, monkeypatch, tmp_path):
    monkeypatch.delenv(chat_upstream.URL_ENV)
    monkeypatch.delenv(chat_upstream.MODEL_ENV)
    settings = chat_upstream.load_settings()
    assert settings.base_url == chat_upstream.DEFAULT_BASE_URL and settings.model == chat_upstream.DEFAULT_MODEL
    assert settings.timeout == chat_upstream.DEFAULT_TIMEOUT_SECONDS
    bridge = tmp_path / "hermes" / chat_upstream.COCKPIT_RUNTIME_FILE
    bridge.parent.mkdir(parents=True)
    bridge.write_text(json.dumps({"model": "bridge-model"}), encoding="utf-8")
    assert chat_upstream.load_settings().model == "bridge-model"
    (config.hub_dir() / chat_upstream.HUB_CONFIG_FILE).write_text(json.dumps(
        {"chat": {"model": "hub-model", "base_url": "http://127.0.0.1:9/v1", "timeout_seconds": 5}}), encoding="utf-8")
    settings = chat_upstream.load_settings()
    assert (settings.model, settings.base_url, settings.timeout) == ("hub-model", "http://127.0.0.1:9/v1", 5.0)
    monkeypatch.setenv(chat_upstream.MODEL_ENV, "env-model")
    assert chat_upstream.load_settings().model == "env-model"
