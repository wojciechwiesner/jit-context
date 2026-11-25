"""Operator Wall: aggregation, ranking, fail-open per source, charter approve (no network, fake ~/.hermes)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import pytest

from health import hub_routes, livestream, mission_data, wall_charters, wall_data, wall_external, wall_readers

NOW = time.time()
DAY = 86400


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    monkeypatch.setattr(wall_readers, "HERMES_HOME", home)
    for job, repo, status, age in [("j1", "alpha", "review", 6 * DAY + 3600), ("j2", "alpha", "review", 1 * DAY),
                                   ("j3", "beta", "running", 60), ("j4", "beta", "failed", DAY),
                                   ("j5", "beta", "lost", 3 * DAY)]:
        write_json(home / "state/code-dispatch" / job / "meta.json",
                   {"job": job, "repo": f"/x/{repo}", "status": status, "started_at": iso(NOW - age - 60),
                    "finished_at": iso(NOW - age)})
    (home / "state/code-dispatch/broken").mkdir()
    (home / "state/code-dispatch/broken/meta.json").write_text("{not json")
    write_json(home / "cron/jobs.json", {"jobs": [{"id": "c1", "name": "nightly-sync"}]})
    db = home / "cron/executions.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, claimed_at TEXT, error TEXT)")
    con.executemany("INSERT INTO executions VALUES (?,?,?,?,?)", [
        ("e1", "c1", "failed", iso(NOW - 3600), "boom"), ("e2", "c1", "failed", iso(NOW - 7200), "older"),
        ("e3", "c2", "failed", iso(NOW - 3 * DAY), "too old"), ("e4", "c3", "completed", iso(NOW), "")])
    con.commit(); con.close()
    flow = {"flow_id": "ksef", "overall_state": "degraded", "checked_at": NOW,
            "edges": [{"edge_id": "a->b", "state": "sla_breach", "last_seen_at": NOW - 600}, {"edge_id": "b->c", "state": "ok"}]}
    write_json(home / "state/jit-hub/autocheck_flows.json", {"updated_at": iso(NOW), "projects": {
        "alpha": {"flows": [flow]}, "beta": {"flows": [{"flow_id": "f", "overall_state": "ok", "edges": []}]}}})
    for slug, status in [("alpha", "draft"), ("beta", "approved")]:
        write_json(home / "state/jit-hub/charters" / f"{slug}.json", {
            "slug": slug, "status": status, "type": "product", "goal": f"goal {slug}", "audience": ["me"],
            "audience_candidates": [{"who": "dominik", "why": "client"}]})
    projects = [{"slug": s, "title": s, "last_commit": {"iso": "x"}, "open_tasks": 0, "blockers": 0,
                 "sessions_7d": 0, "last_activity": NOW - a} for s, a in [("alpha", DAY), ("beta", 2 * DAY), ("old", 30 * DAY)]]
    monkeypatch.setattr(mission_data, "list_projects", lambda: projects)
    monkeypatch.setattr(wall_external, "blocked_cards", lambda: ([{"id": "t1", "title": "stuck", "board": "aipm", "since": NOW - DAY}], 5.0))
    monkeypatch.setattr(wall_external, "nodes", lambda: ([{"name": "omarchy", "online": True, "detail": ""},
                                                          {"name": "windows", "online": False, "detail": ""}], 1.0))
    return home


def test_payload_shape_and_projects(world):
    wall = wall_data.build_wall(NOW)
    assert set(wall) >= {"generated_at", "verdict", "needs_me", "projects", "machines", "charters", "sources"}
    assert {p["slug"] for p in wall["projects"]} == {"alpha", "beta"}  # 'old' is outside 7 days
    alpha = next(p for p in wall["projects"] if p["slug"] == "alpha")
    assert alpha["review_count"] == 2 and alpha["autocheck"] == "degraded" and alpha["charter"]["status"] == "draft"
    assert alpha["audience"] == []  # draft: audience not official yet
    beta = next(p for p in wall["projects"] if p["slug"] == "beta")
    assert beta["audience"] == ["me"]
    assert wall["charters"]["draft"] == 1 and wall["charters"]["approved"] == 1
    assert all(s["ok"] for s in wall["sources"].values())


def test_ranking_and_verdict(world):
    wall = wall_data.build_wall(NOW)
    kinds = [i["kind"] for i in wall["needs_me"]]
    assert kinds == ["autocheck_edge", "cron_failed", "blocked_card", "review", "review", "lost_session"]
    assert len(wall["needs_me"]) == 6 <= wall_data.NEEDS_ME_MAX == 7
    assert wall["needs_me"][3]["what"].endswith("j1")  # oldest review first
    assert wall["needs_me_total"] == 6  # edge + cron + card + 2 reviews + lost
    assert wall["verdict"].startswith("4 rzeczy czekają na Ciebie.")
    assert "2 sesje do przeglądu, najstarsza 6 dni." in wall["verdict"]
    assert wall["verdict"].endswith("Przepływy z błędem: 1.") and wall["level"] == "bad"
    assert wall["machines"]["sessions"] == {"running": 1, "review": 2, "failed": 1, "lost": 1}
    assert wall["machines"]["cron_failed_24h"] == 1  # deduped per job, 3-day-old one dropped


def test_all_clear_verdict(world, monkeypatch):
    for f in (world / "state/code-dispatch").glob("*/meta.json"):
        f.unlink()
    write_json(world / "state/jit-hub/autocheck_flows.json", {"updated_at": iso(NOW), "projects": {
        "alpha": {"flows": [{"flow_id": "f", "overall_state": "ok", "edges": []}]}}})
    con = sqlite3.connect(world / "cron/executions.db")
    con.execute("DELETE FROM executions")
    con.commit(); con.close()
    monkeypatch.setattr(wall_external, "blocked_cards", lambda: ([], 0.0))
    wall = wall_data.build_wall(NOW)
    assert wall["verdict"] == "Nic pilnego nie czeka na Ciebie. Przepływy OK."
    assert wall["level"] == "ok" and wall["needs_me"] == []


def test_broken_cron_db_fails_open(world):
    (world / "cron/executions.db").write_bytes(b"not a database")
    wall = wall_data.build_wall(NOW)
    assert wall["sources"]["cron"]["ok"] is False and wall["machines"]["cron_failed_24h"] is None


def test_each_source_fails_open(world, monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(wall_external, "blocked_cards", boom)
    monkeypatch.setattr(wall_external, "nodes", boom)
    monkeypatch.setattr(mission_data, "list_projects", boom)
    (world / "state/jit-hub/autocheck_flows.json").unlink()
    wall = wall_data.build_wall(NOW)
    for name in ("kanban", "nodes", "projects", "autocheck"):
        assert wall["sources"][name]["ok"] is False
        assert wall["sources"][name]["error"].startswith("brak danych:")
    assert wall["sources"]["sessions"]["ok"] and wall["sources"]["charters"]["ok"]
    assert wall["projects"] == [] and wall["machines"]["nodes"] is None and wall["machines"]["blocked_cards"] is None
    assert "Przepływy: brak danych." in wall["verdict"]  # never a false "OK"


def test_missing_charter_dir_means_no_charter_not_crash(world):
    for f in (world / "state/jit-hub/charters").iterdir():
        f.unlink()
    (world / "state/jit-hub/charters").rmdir()
    wall = wall_data.build_wall(NOW)
    assert wall["sources"]["charters"]["ok"] is False
    assert all(p["charter"] is None and p["charter_known"] is False for p in wall["projects"])


def test_plural_forms():
    forms = ("rzecz", "rzeczy", "rzeczy-")
    assert [wall_data.plural(n, *forms) for n in (1, 2, 4, 5, 12, 22, 25)] == [
        "rzecz", "rzeczy", "rzeczy", "rzeczy-", "rzeczy-", "rzeczy", "rzeczy-"]


def test_parse_nodes():
    nodes = wall_external.parse_nodes('omarchy: ONLINE claude-auth=unknown\nwindows: OFFLINE\nnoise line here\n')
    assert [(n["name"], n["online"]) for n in nodes] == [("omarchy", True), ("windows", False)]


def test_approve_valid_sets_status_audience_and_is_atomic(world):
    result = wall_charters.approve(["alpha"], {"alpha": ["me", "dominik"]}, now=NOW)
    assert result == {"approved": ["alpha"], "skipped": []}
    saved = json.loads((world / "state/jit-hub/charters/alpha.json").read_text())
    assert saved["status"] == "approved" and saved["audience"] == ["me", "dominik"] and saved["approved_at"]
    assert not list((world / "state/jit-hub/charters").glob("*.tmp"))
    again = wall_charters.approve(["alpha"], {})
    assert again["skipped"][0]["slug"] == "alpha"


@pytest.mark.parametrize("slugs,audience,code", [
    (["nope"], {}, 404), (["../etc/passwd"], {}, 404), ([], {}, 400), ("alpha", {}, 400),
    (["alpha"], {"alpha": ["stranger"]}, 400), (["alpha"], {"beta": ["me"]}, 400)])
def test_approve_rejects_invalid_and_writes_nothing(world, slugs, audience, code):
    before = (world / "state/jit-hub/charters/alpha.json").read_text()
    with pytest.raises(wall_charters.CharterError) as err:
        wall_charters.approve(slugs, audience)
    assert err.value.code == code
    assert (world / "state/jit-hub/charters/alpha.json").read_text() == before


@pytest.fixture()
def server(world):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def post(base, body, origin=None, token=None):
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers[hub_routes.CSRF_HEADER] = token
    req = urllib.request.Request(base + "/api/mc/charters/approve", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_http_wall_api_and_page(server):
    with urllib.request.urlopen(server + "/api/mc/wall") as res:
        assert "verdict" in json.load(res)
    with urllib.request.urlopen(server + "/wall") as res:
        html = res.read().decode()
    assert 'name="jit-hub-csrf"' in html and "wall.js" in html
    for asset in ("wall.css", "wall.js", "wall_review.js"):
        with urllib.request.urlopen(f"{server}/static/{asset}") as res:
            assert res.status == 200


def test_http_approve_origin_and_csrf(server, world):
    body = {"slugs": ["alpha"], "audience": {"alpha": ["me"]}}
    assert post(server, body)[0] == 403
    assert post(server, body, origin="https://evil.example", token=hub_routes.csrf_token())[0] == 403
    assert post(server, body, origin=server, token="wrong")[0] == 403
    assert json.loads((world / "state/jit-hub/charters/alpha.json").read_text())["status"] == "draft"
    code, payload = post(server, body, origin=server, token=hub_routes.csrf_token())
    assert code == 200 and payload["approved"] == ["alpha"]
    assert post(server, {"slugs": ["ghost"], "audience": {}}, origin=server, token=hub_routes.csrf_token())[0] == 404


def test_blocked_cards_collapse_to_one_row_per_board(world, monkeypatch):
    cards = [{"id": f"t{i}", "title": "x", "board": "2step-app", "since": NOW - DAY - i} for i in range(21)]
    monkeypatch.setattr(wall_external, "blocked_cards", lambda: (cards, 0.0))
    wall = wall_data.build_wall(NOW)
    rows = [i for i in wall["needs_me"] if i["kind"] == "blocked_card"]
    assert len(rows) == 1 and rows[0]["what"] == "21 zablokowanych kart na tablicy 2step-app"
    assert wall["machines"]["blocked_cards"] == 21


def test_cache_serves_stale_value_while_refreshing():
    wall_external.clear_cache()
    calls = []
    release = threading.Event()

    def build():
        calls.append(1)
        if len(calls) > 1:
            release.wait(2)
        return len(calls)

    assert wall_external.cached("k", 0.0, build) == (1, 0.0)
    value, age = wall_external.cached("k", 0.0, build)  # expired: stale 1 returned at once, refresh in background
    assert value == 1 and age >= 0
    release.set()
    deadline = time.time() + 2
    while wall_external.cached("k", 60.0, build)[0] != 2 and time.time() < deadline:
        time.sleep(0.02)
    assert wall_external.cached("k", 60.0, build)[0] == 2
    wall_external.clear_cache()
