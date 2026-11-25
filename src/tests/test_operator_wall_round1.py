"""Operator Wall round 1: slug normalisation, mirror dedupe, next action, Feedby wording, Polish labels."""
from __future__ import annotations

import time

import pytest

from health import wall_charters, wall_data, wall_external, wall_needs, wall_projects

NOW = time.time()
DAY = 86400
CHARTER = {"status": "approved", "type": "client-delivery", "goal": "g", "audience": ["me"]}


@pytest.mark.parametrize("slug", ["_uni-pro-works", "uni_pro_works", "Uni-Pro-Works", "uni-pro-works"])
def test_charter_found_across_slug_spellings(slug):
    assert wall_charters.find({"uni-pro-works": CHARTER}, slug) is CHARTER


def test_charter_not_found_for_other_project():
    assert wall_charters.find({"uni-pro-works": CHARTER}, "other") is None


def test_normalise_remote_equates_url_forms():
    forms = ["git@github.com:Org/Repo.git", "https://github.com/org/repo", "ssh://git@github.com/org/repo.git/"]
    assert len({wall_projects.normalise_remote(u) for u in forms}) == 1


def test_mirrors_sharing_a_remote_collapse_to_shortest_slug(monkeypatch):
    remotes = {"/a": "github.com/o/jit", "/b": "github.com/o/jit", "/c": "github.com/o/other"}
    monkeypatch.setattr(wall_projects, "remote_of", lambda p: remotes.get(p.get("path"), ""))
    projects = [{"slug": "hermes-jit-context-os", "path": "/b"}, {"slug": "jit-context", "path": "/a"},
                {"slug": "other", "path": "/c"}, {"slug": "no-remote"}]
    kept = {p["slug"]: p for p in wall_projects.collapse_mirrors(projects)}
    assert set(kept) == {"jit-context", "other", "no-remote"}
    assert kept["jit-context"]["mirrors"] == ["hermes-jit-context-os"]


def cards(board, n):
    return [{"id": f"t{i}", "title": "x", "board": board, "since": NOW - DAY} for i in range(n)]


def test_feedby_cards_wording_and_rank_below_review():
    review = {"status": "review", "job": "j1", "project": "alpha", "since": NOW - DAY}
    needs = wall_needs.needs_items(None, [], cards("feedby", 176) + cards("aipm", 2), [review])
    assert [i["kind"] for i in needs] == ["blocked_card", "review", "feedby_decision"]
    assert needs[2]["what"] == "176 zgłoszeń Feedby czeka na Twoją decyzję"
    assert needs[0]["what"] == "2 zablokowane karty na tablicy aipm"
    verdict, level = wall_needs.build_verdict(needs, {"projects": {}}, NOW)
    assert verdict.startswith("1 rzecz czeka na Ciebie. 176 zgłoszeń Feedby czeka na Twoją decyzję.")
    assert "1 sesja do przeglądu" in verdict and level == "bad"


def test_feedby_alone_is_not_urgent():
    needs = wall_needs.needs_items({"projects": {}}, [], cards("feedby", 1), [])
    verdict, level = wall_needs.build_verdict(needs, {"projects": {}}, NOW)
    assert verdict.startswith("Nic pilnego nie czeka na Ciebie. 1 zgłoszenie Feedby czeka na Twoją decyzję.")
    assert level == "warn"


def test_next_action_is_top_needs_row_with_link():
    assert wall_needs.next_action([]) is None
    bad = {"projects": {"alpha": {"state": "degraded", "failing": [{"flow": "ksef", "edge": "a->b", "state": "degraded", "since": NOW}]}}}
    needs = wall_needs.needs_items(bad, [], cards("feedby", 3), [])
    action = wall_needs.next_action(needs)
    assert action["kind"] == "autocheck_edge" and action["link"] == "/mc?project=alpha"
    assert action["text"] == "Przepływ ksef: krok a->b (spowolnione)"


def test_payload_has_next_action_and_polish_text(world_round1):
    wall = world_round1
    assert wall["next_action"] == {k: wall["needs_me"][0][v] for k, v in
                                   {"text": "what", "link": "link", "kind": "kind", "since": "since"}.items()}
    assert "review" not in wall["verdict"] and "krawędź" not in wall["needs_me"][0]["what"]


@pytest.fixture()
def world_round1(tmp_path, monkeypatch):
    from health import mission_data, wall_readers
    monkeypatch.setattr(wall_readers, "HERMES_HOME", tmp_path)
    (tmp_path / "state/jit-hub/charters").mkdir(parents=True)
    (tmp_path / "state/jit-hub/charters/uni-pro-works.json").write_text(
        '{"status": "draft", "type": "client-delivery", "goal": "g", "audience": []}')
    monkeypatch.setattr(mission_data, "list_projects", lambda: [
        {"slug": "_uni-pro-works", "title": "uni", "last_commit": None, "blockers": 0, "last_activity": NOW}])
    monkeypatch.setattr(wall_external, "blocked_cards", lambda: (cards("feedby", 3), 0.0))
    monkeypatch.setattr(wall_external, "nodes", lambda: ([], 0.0))
    wall = wall_data.build_wall(NOW)
    assert wall["projects"][0]["charter"]["type"] == "client-delivery"  # _uni-pro-works found its charter
    return wall
