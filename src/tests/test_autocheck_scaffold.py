"""sota-starter Autocheck: jit init creates the probe folder, never a status file; the cockpit shows real state."""

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import config
from context.autocheck_scaffold import autocheck_init_line, ensure_autocheck_scaffold
from l1.cockpit_sync import regenerate_cockpit

DATA_RE = re.compile(r'<script type="application/json" id="cockpit-data-json">(.*?)</script>', re.S)
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_scaffold_creates_readme_once_and_no_status_file(tmp_path):
    first = ensure_autocheck_scaffold(tmp_path)
    readme = tmp_path / ".planning" / "autocheck" / "README.md"
    assert first["readme_created"] is True and readme.is_file()
    assert first["probes"] == [] and first["status_file_exists"] is False
    assert not (tmp_path / ".planning" / "autocheck.json").exists()
    assert "no probes yet" in autocheck_init_line(first)

    readme.write_text("operator notes", encoding="utf-8")
    (readme.parent / "health.hurl").write_text("# @node: health\nGET http://x/health\nHTTP 200\n", encoding="utf-8")
    second = ensure_autocheck_scaffold(tmp_path)
    assert second["readme_created"] is False
    assert readme.read_text(encoding="utf-8") == "operator notes"
    assert second["probes"] == ["health.hurl"]
    assert "1 probe(s)" in autocheck_init_line(second)


def _build(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    ok, msg = regenerate_cockpit(repo)
    assert ok, msg
    html = (repo / ".planning" / "state.html").read_text(encoding="utf-8")
    return html, json.loads(DATA_RE.search(html).group(1))


@needs_node
def test_cockpit_shows_not_measured_without_status_file(tmp_path, monkeypatch):
    repo = tmp_path / "app"
    ensure_autocheck_scaffold(repo)
    (repo / ".planning" / "autocheck" / "health.hurl").write_text("# @node: h\nGET http://x/h\n", encoding="utf-8")
    html, data = _build(repo, monkeypatch, tmp_path)
    assert data["autocheck"]["exists"] is False
    assert data["autocheck"]["probes"] == ["health.hurl"]
    assert "NIE ZMIERZONO" in html


@needs_node
def test_cockpit_marks_stale_measurement(tmp_path, monkeypatch):
    repo = tmp_path / "app"
    (repo / ".planning").mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    status = {"updated_at": old, "overall_state": "ok", "checks": [], "flows": [{
        "flow_id": "health", "overall_state": "ok", "findings": [],
        "edges": [{"from_node": "probe_started", "to_node": "health", "state": "ok",
                   "completed_on_time": 1, "total_started": 1, "missing_downstream": 0,
                   "sla_breaches": 0, "p95_seconds": 0.12}]}]}
    (repo / ".planning" / "autocheck.json").write_text(json.dumps(status), encoding="utf-8")
    html, data = _build(repo, monkeypatch, tmp_path)
    assert data["autocheck"]["exists"] is True
    assert data["autocheck"]["updatedAt"] == old
    # The overview is rendered at build time: a 5 h old measurement is marked stale, p95 comes from p95_seconds.
    assert "STALE" in html and "nieaktualny" in html
    assert "p95 0.12s" in html
