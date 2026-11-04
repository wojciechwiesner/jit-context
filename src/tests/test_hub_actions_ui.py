"""H18 actions UI: /hub/<slug> carries the four actions and their endpoints; GET /api/hub/report serves reports."""

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import actions, refresher, registry
from hub.actions import report, run_store

META_RE = re.compile(r'<meta name="(jit-hub-[a-z]+)" content="([^"]*)">')
COST_TEXT = "Uruchamia model i może kosztować tokeny"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is needed for the cockpit generator")


def make_repo(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text("# State\n\n## Tasks\n- [ ] H18 actions ui\n", encoding="utf-8")
    (path / ".gitignore").write_text(".planning/state.html\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "first commit"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv(config.HUB_DIR_ENV, str(tmp_path / "hub"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    entry, _ = registry.register_project(make_repo(tmp_path / "actions-demo"))
    result = refresher.refresh_project(entry, force=True)
    assert result.status == refresher.REBUILT, result.detail
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{httpd.server_address[1]}", "entry": entry, "tmp": tmp_path}
    httpd.shutdown()
    httpd.server_close()


def fetch(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def save_run(slug: str, action: str, report_path, status: str = "succeeded") -> dict:
    run = {"id": run_store.new_run_id(action), "slug": slug, "action": action, "label": actions.ACTION_LABELS[action],
           "status": status, "created": run_store.now_iso(), "report_path": str(report_path) if report_path else None}
    return run_store.save(run)


def test_cockpit_from_hub_has_the_four_actions_and_their_endpoints(served):
    slug = served["entry"]["slug"]
    status, html = fetch(f"{served['base']}/hub/{slug}")
    assert status == 200
    for action, label in actions.ACTION_LABELS.items():
        assert f'id="action-btn-{action}" data-action="{action}"' in html, action
        assert f"<span>{label}</span>" in html, label
    assert COST_TEXT in html and 'id="action-confirm-modal"' in html and 'id="action-report-viewer"' in html
    head = html[html.index("<head>"):html.index("</head>")]
    metas = dict(META_RE.findall(head))
    assert metas[hub_routes.ACTIONS_META_NAME] == hub_routes.ACTIONS_ROUTE
    assert metas[hub_routes.RUNS_META_NAME] == hub_routes.RUNS_ROUTE
    assert metas[hub_routes.REPORT_META_NAME] == hub_routes.REPORT_ROUTE
    assert metas[hub_routes.SLUG_META_NAME] == slug and metas[hub_routes.CSRF_META_NAME] == hub_routes.csrf_token()
    # the runs endpoint announced to the page answers for the announced slug (no runs, nothing invented)
    status, body = fetch(f"{served['base']}{metas[hub_routes.RUNS_META_NAME]}?slug={slug}")
    assert status == 200 and json.loads(body)["runs"] == []


def test_file_cockpit_has_no_action_endpoints_but_links_to_the_hub(served):
    slug = served["entry"]["slug"]
    # the cockpit is git-ignored in the demo repo, so the generator writes it into the project
    html = (Path(served["entry"]["path"]) / ".planning" / "state.html").read_text(encoding="utf-8")
    assert META_RE.search(html) is None
    assert f'id="actions-open-hub" href="http://127.0.0.1:8767/hub/{slug}#actions"' in html


def test_report_route_serves_the_markdown_of_a_run(served):
    slug = served["entry"]["slug"]
    path = report.reports_dir(slug) / "2026-11-04-audit360.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Audyt 360\n\n<b>tekst</b> z dowodem README.md:1\n", encoding="utf-8")
    run = save_run(slug, "audit360", path)
    status, body = fetch(f"{served['base']}{hub_routes.REPORT_ROUTE}?run={run['id']}")
    payload = json.loads(body)
    assert status == 200 and payload["markdown"].startswith("# Audyt 360") and payload["run"]["id"] == run["id"]
    assert payload["path"] == str(path.resolve())


def test_report_route_errors_are_explicit(served):
    slug = served["entry"]["slug"]
    outside = served["tmp"] / "secret.md"
    outside.write_text("nie dla UI\n", encoding="utf-8")
    foreign = save_run(slug, "security", outside)
    pending = save_run(slug, "market", None, status="running")
    missing = save_run(slug, "monetization", report.reports_dir(slug) / "gone.md")
    cases = [(foreign["id"], 403, "poza katalogiem"), (pending["id"], 404, "nie ma raportu"),
             (missing["id"], 404, "nie można odczytać"), ("20261104T101010-audit360-000000", 404, "nie ma uruchomienia"),
             ("../../etc/passwd", 404, "nieprawidłowy identyfikator"), ("", 404, "nieprawidłowy identyfikator")]
    for run_id, code, fragment in cases:
        status, body = fetch(f"{served['base']}{hub_routes.REPORT_ROUTE}?run={urllib.request.quote(run_id)}")
        payload = json.loads(body)
        assert status == code and fragment in payload["error"], run_id
        assert "markdown" not in payload
