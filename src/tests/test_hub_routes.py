"""Hub API on the Mission Control server: real HTTP on an ephemeral port, tmp registry, fake cockpit builder."""

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import overview, refresher, registry
from hub import stats as hub_stats

FAKE_BUILDER = """
const fs = require("fs"), path = require("path");
const args = process.argv.slice(2);
const i = args.indexOf("--out");
const out = i >= 0 ? args.splice(i, 2)[1] : null;
const root = path.resolve(args[0]);
fs.appendFileSync(process.env.FAKE_BUILDER_LOG, root + "\\n");
const target = out || path.join(root, ".planning", "state.html");
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.writeFileSync(target, "<html><head><title>t</title></head><body>fresh build</body></html>");
"""
STATE_MD = """# State

## Tasks
- [ ] H13 hub api
- [ ] H14 hub ui
- [x] H12 stats

## Blokery
- [ ] waiting for review
"""
META_RE = re.compile(r'<meta name="jit-hub-csrf" content="([^"]+)">')


def make_repo(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text(STATE_MD, encoding="utf-8")
    (path / ".gitignore").write_text(".planning/state.html\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "first commit"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv(config.HUB_DIR_ENV, str(tmp_path / "hub"))
    script = tmp_path / "fake_builder.js"
    script.write_text(FAKE_BUILDER, encoding="utf-8")
    log = tmp_path / "builds.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv(config.COCKPIT_BUILDER_ENV, str(script))
    monkeypatch.setenv("FAKE_BUILDER_LOG", str(log))
    monkeypatch.delenv(hub_routes.ORIGINS_ENV, raising=False)
    repo = make_repo(tmp_path / "demo")
    entry, _ = registry.register_project(repo)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield {"base": f"http://127.0.0.1:{port}", "origin": f"http://127.0.0.1:{port}", "slug": entry["slug"], "path": entry["path"],
           "repo": repo, "builds": lambda: [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]}
    httpd.shutdown()
    httpd.server_close()


def request(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def get_json(url):
    status, body = request(url)
    return status, json.loads(body)


def page_token(hub):
    status, html = request(f"{hub['base']}/hub/{hub['slug']}")
    assert status == 200
    return META_RE.search(html).group(1)


def test_projects_lists_registry_with_honest_missing_sections(hub):
    status, payload = get_json(f"{hub['base']}/api/hub/projects")
    assert status == 200
    [row] = payload["projects"]
    assert row["slug"] == hub["slug"] and row["exists"] is True
    assert row["freshness"]["status"] == overview.NEVER_BUILT
    assert row["last_activity"]["branch"] == "main" and row["last_activity"]["subject"] == "first commit"
    assert row["open_tasks"]["count"] == 3  # unchecked items, the blocker included
    assert row["blockers"] == {"count": 1, "items": ["waiting for review"]}
    assert "missing" in row["tokens_7d"] and "missing" in row["top_suggestion"]


def test_version_and_unknown_slug(hub):
    status, payload = get_json(f"{hub['base']}/api/hub/version?slug={hub['slug']}")
    assert status == 200 and payload["built_at"] is None and payload["signature"] is None
    assert get_json(f"{hub['base']}/api/hub/version?slug=nope")[0] == 404
    assert get_json(f"{hub['base']}/hub/nope")[0] == 404
    assert get_json(f"{hub['base']}/hub/{hub['slug']}")[0] == 404  # nothing built yet


@pytest.mark.parametrize("headers_for", [
    lambda hub, token: {},
    lambda hub, token: {"Origin": "https://evil.example", "X-JIT-Hub-CSRF": token},
    lambda hub, token: {"Origin": "null", "X-JIT-Hub-CSRF": token},
    lambda hub, token: {"Origin": hub["origin"]},
    lambda hub, token: {"Origin": hub["origin"], "X-JIT-Hub-CSRF": "wrong-token"},
])
def test_refresh_rejects_bad_origin_or_token(hub, headers_for):
    (hub["repo"] / ".planning" / "state.html").write_text("<html><head></head></html>", encoding="utf-8")
    token = page_token(hub)
    status, body = request(f"{hub['base']}/api/hub/refresh?slug={hub['slug']}", "POST", headers_for(hub, token))
    assert status == 403 and "error" in json.loads(body)
    assert hub["builds"]() == []


def test_refresh_rebuilds_and_bumps_version(hub):
    (hub["repo"] / ".planning" / "state.html").write_text("<html><head></head>old</html>", encoding="utf-8")
    token = page_token(hub)
    headers = {"Origin": hub["origin"], "X-JIT-Hub-CSRF": token}
    status, body = request(f"{hub['base']}/api/hub/refresh?slug={hub['slug']}", "POST", headers)
    payload = json.loads(body)
    assert status == 200 and payload["status"] == refresher.REBUILT and payload["built_at"]
    assert hub["builds"]() == [hub["path"]]
    status, version = get_json(f"{hub['base']}/api/hub/version?slug={hub['slug']}")
    assert version["signature"] == payload["signature"] and version["built_at"] == payload["built_at"]
    status, html = request(f"{hub['base']}/hub/{hub['slug']}")
    assert "fresh build" in html and html.index("jit-hub-csrf") > html.index("<head>")
    row = get_json(f"{hub['base']}/api/hub/projects")[1]["projects"][0]
    assert row["freshness"]["status"] == overview.FRESH
    # a second forced rebuild runs even though nothing changed
    assert request(f"{hub['base']}/api/hub/refresh?slug={hub['slug']}", "POST", headers)[0] == 200
    assert len(hub["builds"]()) == 2


def test_refresh_unknown_slug_and_route_after_guard(hub):
    (hub["repo"] / ".planning" / "state.html").write_text("<html></html>", encoding="utf-8")
    headers = {"Origin": f"http://localhost:{hub['origin'].rsplit(':', 1)[1]}", "X-JIT-Hub-CSRF": page_token(hub)}
    assert request(f"{hub['base']}/api/hub/refresh?slug=nope", "POST", headers)[0] == 404
    assert request(f"{hub['base']}/api/hub/other", "POST", headers)[0] == 404
    assert request(f"{hub['base']}/api/mc/projects", "POST", headers)[0] == 404


def test_hub_serves_the_freshest_cockpit(hub):
    repo_copy = hub["repo"] / ".planning" / "state.html"
    repo_copy.write_text("<html>repo copy</html>", encoding="utf-8")
    hub_copy = refresher.hub_cockpit_path(hub["slug"])
    hub_copy.parent.mkdir(parents=True, exist_ok=True)
    hub_copy.write_text("<html>hub copy</html>", encoding="utf-8")
    old = time.time() - 3600
    os.utime(repo_copy, (old, old))
    status, html = request(f"{hub['base']}/hub/{hub['slug']}")
    assert status == 200 and "hub copy" in html and html.startswith('<meta name="jit-hub-csrf"')
    os.utime(hub_copy, (old - 60, old - 60))
    assert "repo copy" in request(f"{hub['base']}/hub/{hub['slug']}")[1]


def test_tokens_and_top_suggestion_come_from_the_stats_file(hub):
    today = date.today()
    days = [{"day": today.isoformat(), "total_tokens": 120}, {"day": "2000-01-01", "total_tokens": 999}]
    doc = {"generated_at": "2026-11-04T10:00:00+01:00", "usage": {"days": days},
           "suggestions": {"suggestions": [{"rule_id": "state_stale", "severity": "high"}]}}
    path = hub_stats.stats_path(hub["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    row = get_json(f"{hub['base']}/api/hub/projects")[1]["projects"][0]
    assert row["tokens_7d"]["total_tokens"] == 120 and row["tokens_7d"]["days_with_data"] == 1
    assert row["top_suggestion"]["rule_id"] == "state_stale"


def test_stats_sections_report_errors_and_empty_windows():
    assert overview.tokens_last_days({"usage": {"error": "db locked"}}, date(2026, 11, 4)) == {"error": "db locked"}
    empty = overview.tokens_last_days({"usage": {"days": []}}, date(2026, 11, 4))
    assert "missing" in empty and empty["since"] == "2026-10-29"
    assert overview.top_suggestion({"suggestions": {"suggestions": []}}) is None
    assert overview.top_suggestion({"suggestions": {"error": "boom"}}) == {"error": "boom"}


def test_allowed_origins_env(monkeypatch):
    monkeypatch.setenv(hub_routes.ORIGINS_ENV, "https://Hub.Example/ , ")
    origins = hub_routes.allowed_origins(8767)
    assert "https://hub.example" in origins and "http://127.0.0.1:8767" in origins
    assert "https://live.borg.tools" not in origins
