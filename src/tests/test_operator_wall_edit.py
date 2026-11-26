"""Operator Wall: owner edits of charters (answers, fields, audience) over the update route."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from health import hub_routes, livestream, wall_charter_edit, wall_charters, wall_readers

QUESTIONS = ["Ile zgłoszeń tygodniowo?", "Kto jest klientem?"]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    monkeypatch.setattr(wall_readers, "HERMES_HOME", root)
    folder = root / "state/jit-hub/charters"
    folder.mkdir(parents=True)
    for slug, status in [("alpha", "draft"), ("beta", "approved")]:
        (folder / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "status": status, "type": "product", "goal": "orig goal", "success": "orig success", "cadence": "weekly",
            "audience": ["me"], "audience_candidates": [{"who": "dominik", "why": "client"}], "questions": QUESTIONS}))
    return folder


def saved(home, slug="alpha"):
    return json.loads((home / f"{slug}.json").read_text())


def req(**extra):
    return {"slug": "alpha", **extra}


def test_update_stores_answers_fields_audience_and_keeps_questions(home):
    out = wall_charter_edit.update(req(
        answers=[{"question": QUESTIONS[0], "answer": " 14 "}, {"question": QUESTIONS[1], "answer": ""}],
        fields={"type": "client-delivery", "goal": "new goal", "success": "new success", "cadence": "daily"},
        audience=["dominik", "ola_2"]))
    data = saved(home)
    assert out["status"] == "draft" and data["status"] == "draft" and data["edited_at"]
    assert data["questions"] == QUESTIONS
    assert [(a["question"], a["answer"]) for a in data["answers"]] == [(QUESTIONS[0], "14")] and data["answers"][0]["answered_at"]
    assert (data["type"], data["goal"], data["cadence"]) == ("client-delivery", "new goal", "daily")
    assert data["audience"] == ["me", "dominik", "ola_2"]


def test_empty_answer_removes_existing_and_unchanged_keeps_timestamp(home):
    wall_charter_edit.update(req(answers=[{"question": QUESTIONS[0], "answer": "a"}]), now=1000)
    first = saved(home)["answers"][0]["answered_at"]
    wall_charter_edit.update(req(answers=[{"question": QUESTIONS[0], "answer": "a"}]), now=9000)
    assert saved(home)["answers"][0]["answered_at"] == first
    wall_charter_edit.update(req(answers=[{"question": QUESTIONS[0], "answer": ""}]))
    assert saved(home)["answers"] == []


def test_draft_original_kept_once(home):
    wall_charter_edit.update(req(fields={"goal": "second"}))
    wall_charter_edit.update(req(fields={"goal": "third", "type": "dormant"}))
    data = saved(home)
    assert data["draft_original"] == {"type": "product", "goal": "orig goal", "success": "orig success"}
    assert data["goal"] == "third"


def test_unchanged_fields_do_not_create_draft_original(home):
    wall_charter_edit.update(req(fields={"goal": "orig goal", "cadence": "daily"}))
    assert "draft_original" not in saved(home)


def test_approved_charter_stays_editable_and_approved(home):
    wall_charter_edit.update({"slug": "beta", "answers": [{"question": QUESTIONS[1], "answer": "ACME"}]})
    data = saved(home, "beta")
    assert data["status"] == "approved" and data["answers"][0]["answer"] == "ACME"


def test_approve_after_update_accepts_added_person(home):
    wall_charter_edit.update(req(audience=["ola"]))
    result = wall_charters.approve(["alpha"], {"alpha": ["me", "ola"]})
    assert result["approved"] == ["alpha"] and saved(home)["audience"] == ["me", "ola"]


@pytest.mark.parametrize("request_body,code", [
    ({"slug": "ghost"}, 404), ({"slug": "../etc"}, 404), ({}, 404), ({"slug": 5}, 404),
    ({"slug": "alpha", "fields": {"type": "weird"}}, 400),
    ({"slug": "alpha", "fields": {"cadence": "hourly"}}, 400),
    ({"slug": "alpha", "fields": {"owner": "x"}}, 400),
    ({"slug": "alpha", "fields": {"goal": "x" * 601}}, 400),
    ({"slug": "alpha", "answers": [{"question": "nieznane?", "answer": "x"}]}, 400),
    ({"slug": "alpha", "answers": [{"question": QUESTIONS[0], "answer": "x" * 601}]}, 400),
    ({"slug": "alpha", "audience": ["Dominik"]}, 400),
    ({"slug": "alpha", "audience": ["a"]}, 400),
    ({"slug": "alpha", "audience": ["1abc"]}, 400),
    ({"slug": "alpha", "audience": "dominik"}, 400),
])
def test_invalid_requests_rejected_and_write_nothing(home, request_body, code):
    before = (home / "alpha.json").read_text()
    with pytest.raises(wall_charters.CharterError) as err:
        wall_charter_edit.update(request_body)
    assert err.value.code == code
    assert (home / "alpha.json").read_text() == before


def test_max_length_text_is_accepted(home):
    wall_charter_edit.update(req(fields={"goal": "x" * 600}))
    assert len(saved(home)["goal"]) == 600


@pytest.fixture()
def server(home):
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
    request = urllib.request.Request(base + "/api/mc/charters/update", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(request) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_http_update_origin_csrf_and_success(server, home):
    body = req(fields={"goal": "via http"})
    assert post(server, body)[0] == 403
    assert post(server, body, origin="https://evil.example", token=hub_routes.csrf_token())[0] == 403
    assert post(server, body, origin=server, token="wrong")[0] == 403
    assert saved(home)["goal"] == "orig goal"
    code, payload = post(server, body, origin=server, token=hub_routes.csrf_token())
    assert code == 200 and payload["saved"] == "alpha" and saved(home)["goal"] == "via http"
    assert post(server, {"slug": "ghost"}, origin=server, token=hub_routes.csrf_token())[0] == 404
