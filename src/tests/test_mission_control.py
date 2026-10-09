"""Mission Control: access guard, project/session data and HTTP routes (no network)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from health import livestream, mission_data, mission_project
from health.mission_access import check_access


@pytest.fixture()
def fake_world(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    (root / "alpha" / ".planning").mkdir(parents=True)
    (root / "alpha" / ".planning" / "STATE.md").write_text(
        "# STATE\n- [ ] ship it\n- [x] done\n\n## Blockers\n- waiting for keys\n\n## Next\n- [ ] later\n")
    (root / "alpha" / ".planning" / "ARCHITECTURE.mmd").write_text("graph TD\n  A-->B\n")
    (root / "beta" / ".planning").mkdir(parents=True)
    (root / "beta" / ".planning" / "state.html").write_text("<html>beta cockpit</html>")
    (root / "alpha2" / ".planning").mkdir(parents=True)
    (root / "no_planning").mkdir()

    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT, title TEXT, source TEXT, model TEXT, started_at REAL,"
                " cwd TEXT, message_count INT, tool_call_count INT)")
    con.execute("CREATE TABLE messages (session_id TEXT, timestamp REAL)")
    now = time.time()
    rows = [("s-alpha", "alpha work", str(root / "alpha"), now - 60),
            ("s-alpha-sub", "subdir", str(root / "alpha" / "src"), now - 7200),
            ("s-alpha2", "sibling prefix", str(root / "alpha2"), now - 30),
            ("s-old", "too old", str(root / "alpha"), now - 30 * 86400)]
    for sid, title, cwd, started in rows:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)", (sid, title, "cli", "m", started, cwd, 3, 1))
        con.execute("INSERT INTO messages VALUES (?,?)", (sid, started + 10))
    con.commit()
    con.close()

    monkeypatch.setattr(mission_data, "PROJECTS_ROOT", root)
    monkeypatch.setattr(mission_data, "COCKPIT_EXPORT", tmp_path / "missing_export.js")
    monkeypatch.setattr(mission_data, "OBSIDIAN_PROJECTS", tmp_path / "vault")
    monkeypatch.setattr("health.livestream_session.STATE_DB", db, raising=False)
    monkeypatch.setattr(mission_data, "_ro", lambda: _ro_conn(db))
    mission_data._cache.clear()
    yield root
    mission_data._cache.clear()


@contextmanager
def _ro_conn(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def test_access_matrix(monkeypatch):
    monkeypatch.setenv("JIT_MC_TRUSTED_PROXIES", "100.118.47.46")
    assert check_access("127.0.0.1", {}).via == "local"
    sso = check_access("100.118.47.46", {"X-Forwarded-Email": "wojciech@theones.io"})
    assert sso.allowed and sso.user == "wojciech@theones.io" and sso.via == "sso"
    assert not check_access("100.118.47.46", {}).allowed
    assert not check_access("192.168.100.50", {"X-Forwarded-Email": "spoof@x.io"}).allowed


def test_list_projects_counts(fake_world):
    projects = {p["slug"]: p for p in mission_data.list_projects()}
    assert set(projects) == {"alpha", "alpha2", "beta"}
    assert projects["alpha"]["open_tasks"] == 2
    assert projects["alpha"]["blockers"] == 1
    assert projects["alpha"]["sessions_7d"] == 2  # exact cwd + subdir; sibling alpha2 excluded


def test_sessions_match_project_and_subdirs_only(fake_world):
    ids = [s["id"] for s in mission_data.list_sessions("alpha", hours=168, limit=10)]
    assert ids == ["s-alpha", "s-alpha-sub"]
    assert mission_data.list_sessions("alpha", hours=168)[0]["live"] is True
    with pytest.raises(KeyError):
        mission_data.list_sessions("../etc")


def test_project_detail_rejects_traversal_and_falls_back(fake_world):
    assert mission_project.project_detail("../etc") is None
    assert mission_project.project_detail("nope") is None
    detail = mission_project.project_detail("alpha")
    assert detail["cockpit_error"]  # export.js missing -> explicit error, not silent
    assert detail["diagram"]["mermaid"].startswith("graph TD")
    assert detail["state"]["open_count"] == 2
    assert detail["cockpit_url"] is None
    assert mission_project.project_detail("beta")["cockpit_url"] == "/cockpit/beta"


@pytest.fixture()
def server(fake_world):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_http_routes(server):
    status, body = _get(server + "/api/mc/projects")
    assert status == 200 and {p["slug"] for p in json.loads(body)["projects"]} >= {"alpha", "beta"}
    assert _get(server + "/api/mc/whoami") == (200, b'{"user": null, "via": "local"}')
    assert _get(server + "/cockpit/beta") == (200, b"<html>beta cockpit</html>")
    assert _get(server + "/cockpit/..%2Fetc")[0] == 404
    assert _get(server + "/api/mc/project?slug=nope")[0] == 404
    assert _get(server + "/api/mc/sessions?project=nope")[0] == 404
    status, page = _get(server + "/mc")
    assert status == 200 and b"Mission Control" in page
    assert _get(server + "/static/mission.js")[0] == 200
