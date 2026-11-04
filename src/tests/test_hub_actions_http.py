"""Hub action routes through the real Mission Control handler with a fake agent command; no model call."""

import json
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import registry
from hub.actions import agent, runner

FAKE_AGENT = Path(__file__).parent / "fake_hub_agent.py"
POLL_SECONDS = 10
SLEEP_SECONDS = 0.8


def make_repo(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text("# State\n\n**Projekt:** demo\n", encoding="utf-8")
    (path / "README.md").write_text("# Demo\n", encoding="utf-8")
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
    vault = tmp_path / "vault" / "projects"
    vault.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECTS_DIR", vault)
    monkeypatch.setenv("FAKE_AGENT_LOG", str(tmp_path / "agent-log"))
    monkeypatch.setenv(agent.AGENT_CMD_ENV, f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_AGENT))}")
    entry, _ = registry.register_project(make_repo(tmp_path / "demo"))
    runner.set_default_runner(runner.Runner(timeout=POLL_SECONDS))
    server = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{server.server_address[1]}", "slug": entry["slug"], "vault": vault}
    runner.default_runner().wait_idle()
    runner.set_default_runner(None)
    server.shutdown()
    server.server_close()


def request(env, path, payload=None, token=None, origin=None):
    headers = {"Origin": origin or env["base"], hub_routes.CSRF_HEADER: token or hub_routes.csrf_token(),
               "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(env["base"] + path, data=data, method="POST" if data else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def start(env, action="audit360", slug=None):
    return request(env, hub_routes.ACTIONS_ROUTE, {"slug": slug or env["slug"], "action": action})


def wait_finished(env, run_id):
    deadline = time.monotonic() + POLL_SECONDS
    while time.monotonic() < deadline:
        status, body = request(env, f"{hub_routes.RUNS_ROUTE}?slug={env['slug']}")
        assert status == 200
        run = next(item for item in body["runs"] if item["id"] == run_id)
        if run["status"] not in ("queued", "running"):
            return run, body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def test_post_action_queues_a_run_and_runs_lists_the_report(env):
    status, body = start(env)
    assert status == 202 and body["run"]["status"] == "queued" and body["run"]["slug"] == env["slug"]
    run, listing = wait_finished(env, body["run"]["id"])
    assert run["status"] == "succeeded" and run["cost"] == 0.0123 and run["usage"]["output_tokens"] == 50
    assert Path(run["report_path"]).is_file() and Path(run["report_path"]).parent.name == env["slug"]
    assert Path(run["obsidian_path"]).parent == env["vault"] / env["slug"] / "reports"
    assert listing["max_concurrent"] == runner.MAX_CONCURRENT_RUNS and listing["total"] == 1
    assert [item["id"] for item in listing["actions"]] == ["audit360", "security", "market", "monetization"]
    status, everything = request(env, hub_routes.RUNS_ROUTE)
    assert status == 200 and everything["slug"] is None and len(everything["runs"]) == 1


def test_failed_agent_run_is_listed_with_its_error(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_MODE", "fail")
    status, body = start(env, action="security")
    run, _ = wait_finished(env, body["run"]["id"])
    assert status == 202 and run["status"] == "failed" and "boom" in run["error"] and run["report_path"] is None


def test_duplicate_action_is_409_while_active(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_SLEEP", str(SLEEP_SECONDS))
    first_status, first = start(env, action="market")
    status, body = start(env, action="market")
    assert first_status == 202 and status == 409 and body["run"]["id"] == first["run"]["id"]
    wait_finished(env, first["run"]["id"])


@pytest.mark.parametrize("payload, code, fragment", [
    ({"slug": "demo", "action": "deploy"}, 400, "nieznana akcja"),
    ({"action": "market"}, 400, "brak pola slug"),
    ({"slug": "nope", "action": "market"}, 404, "unknown project"),
])
def test_bad_requests(env, payload, code, fragment):
    status, body = request(env, hub_routes.ACTIONS_ROUTE, payload)
    assert status == code and fragment in body["error"]


def test_post_without_csrf_or_with_foreign_origin_is_403(env):
    payload = {"slug": env["slug"], "action": "market"}
    assert request(env, hub_routes.ACTIONS_ROUTE, payload, token="wrong")[0] == 403
    assert request(env, hub_routes.ACTIONS_ROUTE, payload, origin="https://evil.example")[0] == 403
    status, body = request(env, f"{hub_routes.RUNS_ROUTE}?slug={env['slug']}")
    assert status == 200 and body["runs"] == []


def test_runs_for_unknown_slug_is_404(env):
    assert request(env, f"{hub_routes.RUNS_ROUTE}?slug=nope")[0] == 404
