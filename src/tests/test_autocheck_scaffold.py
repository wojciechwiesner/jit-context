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
    contracts = tmp_path / ".planning" / "contracts.yaml"
    assert first["contracts_created"] is True and contracts.is_file()
    # template is fully commented out: nothing becomes active by itself
    assert all(not line.strip() or line.lstrip().startswith("#") for line in contracts.read_text().splitlines())

    readme.write_text("operator notes", encoding="utf-8")
    (readme.parent / "health.hurl").write_text("# @node: health\nGET http://x/health\nHTTP 200\n", encoding="utf-8")
    second = ensure_autocheck_scaffold(tmp_path)
    assert second["readme_created"] is False
    assert second["contracts_created"] is False
    assert readme.read_text(encoding="utf-8") == "operator notes"
    assert second["probes"] == ["health.hurl"]
    assert "1 probe(s)" in autocheck_init_line(second)


def _build(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    if not (repo / ".git").exists():
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


@needs_node
def test_cockpit_renders_behavior_contracts(tmp_path, monkeypatch):
    repo = tmp_path / "app"
    ensure_autocheck_scaffold(repo)
    html, data = _build(repo, monkeypatch, tmp_path)
    assert data["behaviorContracts"]["exists"] is False and data["behaviorContracts"]["hasDefinition"] is True
    assert "Kontrakty zachowania" in html

    now = datetime.now(timezone.utc).isoformat()
    result = {"project": "app", "checked_at": now, "overall_state": "violated", "contracts": [
        {"contract_id": "ok_one", "when": "Klient placi", "then": "dostaje e-mail", "severity": "high",
         "state": "ok", "violation_count": 0, "sample_ids": [], "error": None, "duration_ms": 12.0},
        {"contract_id": "bad_one", "when": "Kod zczytany", "then": "wizyta zamknieta", "severity": "high",
         "state": "violated", "violation_count": 2, "sample_ids": ["V-1", "V-2"], "error": None, "duration_ms": 9.0}]}
    (repo / ".planning" / "contracts.json").write_text(json.dumps(result), encoding="utf-8")
    html, data = _build(repo, monkeypatch, tmp_path)
    assert data["behaviorContracts"]["overallState"] == "violated"
    assert "NARUSZONY" in html and "V-1, V-2" in html and "wizyta zamknieta" in html
    assert html.index("Kod zczytany") < html.index("Klient placi")  # violations first
