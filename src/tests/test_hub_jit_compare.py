"""Observational JIT comparison on synthetic session_days rollups: grouping, medians, low-n label, no savings."""

import argparse
import json
from datetime import date

import pytest

from hub import jit_compare, jit_compare_report
from hub import usage_store as store
from hub.usage import ProjectResolver

DAY = "2026-11-02"
OTHER_DAY = "2026-11-03"
PROJECT_PATH = "/work/alpha"
PROJECTS = [{"slug": "alpha", "path": PROJECT_PATH}]
FORBIDDEN_KEY_PARTS = ("sav", "avoid", "delta", "diff", "reduc", "gain", "oszcz")


def claude_day(conn, session, day=DAY, turns=2, inp=100, out=50, cread=800, cwrite=50, unit=None, path=PROJECT_PATH):
    identity = {"session_id": session, "path": path, "scope": None}
    delta = {"turns": turns, "input_tokens": inp, "output_tokens": out, "cache_read_tokens": cread,
             "cache_write_tokens": cwrite, "api_calls": turns}
    store.add_to_day(conn, "claude", unit or f"{session}.jsonl", day, identity, delta)


def capsule(conn, session, day=DAY, capsules=1, scope="alpha"):
    identity = {"session_id": session, "path": None, "scope": scope}
    store.add_to_day(conn, "jit", f"{scope}/{session}/overlay_{session}.db", day, identity,
                     {"turns": 1, "capsules": capsules, "capsule_tokens": 300 * capsules})


def hermes_session(conn, session, day=DAY, inp=1000, cread=3000, path=PROJECT_PATH):
    store.replace_unit(conn, "hermes", session, [{
        "day": day, "session_id": session, "path": path, "scope": None, "input_tokens": inp, "output_tokens": 10,
        "cache_read_tokens": cread, "cache_write_tokens": 0, "turns": 0, "api_calls": 4, "capsules": 0,
        "capsule_tokens": 0, "hook_ms": 0, "cost_usd": None,
    }])


@pytest.fixture
def conn(tmp_path):
    connection = store.connect(tmp_path / "usage.sqlite")
    yield connection
    connection.close()


def compare(conn, **kwargs):
    return jit_compare.build_comparison(conn, ProjectResolver(PROJECTS), **kwargs)


def all_keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from all_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from all_keys(inner)


def test_low_n_groups_are_labelled_and_medians_computed(conn):
    claude_day(conn, "on-1", turns=2, inp=100, out=100, cread=700, cwrite=100)   # 1000 tok, 2 turns
    claude_day(conn, "on-2", turns=4, inp=200, out=200, cread=1400, cwrite=200)  # 2000 tok, 4 turns
    claude_day(conn, "on-3", turns=1, inp=100, out=0, cread=0, cwrite=0)         # 100 tok, 1 turn
    claude_day(conn, "off-1", turns=5, inp=500, out=0, cread=0, cwrite=500)
    for session in ("on-1", "on-2", "on-3"):
        capsule(conn, session)
    result = compare(conn)
    assert result["label"] == "obserwacja, nie eksperyment"
    [row] = result["rows"]
    assert (row["project"], row["day"], row["registered"]) == ("alpha", DAY, True)
    assert row["jit_on"]["n"] == 3 and row["jit_off"]["n"] == 1
    assert row["enough_data"] is False and row["warning"] == "za mało danych"
    on = row["jit_on"]["metrics"]
    assert on["tokens_per_turn"] == {"median": 500.0, "n": 3}
    assert on["turns_per_session"] == {"median": 2.0, "n": 3}
    assert on["cache_read_share"]["median"] == pytest.approx(0.7 / 0.9)
    assert row["jit_off"]["metrics"]["cache_read_share"] == {"median": 0.0, "n": 1}
    assert on["tool_errors_per_session"] == {"median": None, "n": 0}


def test_twenty_sessions_per_group_clear_the_low_n_label(conn):
    for i in range(20):
        claude_day(conn, f"on-{i}", turns=2)
        capsule(conn, f"on-{i}")
        claude_day(conn, f"off-{i}", turns=3)
    [row] = compare(conn)["rows"]
    assert row["jit_on"]["n"] == 20 and row["jit_off"]["n"] == 20
    assert row["enough_data"] is True and row["warning"] is None
    assert row["jit_off"]["metrics"]["turns_per_session"]["median"] == 3.0


def test_nineteen_in_one_group_keeps_the_low_n_label(conn):
    for i in range(25):
        claude_day(conn, f"on-{i}")
        capsule(conn, f"on-{i}")
    for i in range(19):
        claude_day(conn, f"off-{i}")
    [row] = compare(conn)["rows"]
    assert row["warning"] == "za mało danych"


def test_output_has_no_savings_field(conn):
    for i in range(20):
        claude_day(conn, f"on-{i}", turns=1, inp=10)
        capsule(conn, f"on-{i}")
        claude_day(conn, f"off-{i}", turns=1, inp=1000)
    result = compare(conn)
    bad = [key for key in all_keys(result) if any(part in key.lower() for part in FORBIDDEN_KEY_PARTS)]
    assert bad == []
    assert set(result["rows"][0]) == {"project", "registered", "day", "jit_on", "jit_off", "enough_data", "warning"}
    assert set(result["rows"][0]["jit_on"]) == {"n", "sources", "metrics"}


def test_jit_flag_is_per_session_and_needs_a_capsule(conn):
    claude_day(conn, "s-on", day=DAY)
    claude_day(conn, "s-on", day=OTHER_DAY)
    capsule(conn, "s-on", day=OTHER_DAY)
    claude_day(conn, "s-zero")
    capsule(conn, "s-zero", capsules=0)
    rows = {row["day"]: row for row in compare(conn)["rows"]}
    assert rows[DAY]["jit_on"]["n"] == 1 and rows[DAY]["jit_off"]["n"] == 1
    assert rows[OTHER_DAY]["jit_on"]["n"] == 1 and rows[OTHER_DAY]["jit_off"]["n"] == 0


def test_units_of_one_session_are_summed_and_jit_rows_are_not_sessions(conn):
    claude_day(conn, "s1", turns=2, inp=100, out=0, cread=0, cwrite=0)
    claude_day(conn, "s1", turns=0, inp=300, out=0, cread=0, cwrite=0, unit="s1/subagents/agent-a.jsonl")
    capsule(conn, "only-jit")
    [row] = compare(conn)["rows"]
    assert row["jit_on"]["n"] == 0 and row["jit_off"]["n"] == 1
    assert row["jit_off"]["metrics"]["tokens_per_turn"]["median"] == 200.0


def test_hermes_turns_are_unknown_not_zero(conn):
    hermes_session(conn, "h1", inp=1000, cread=3000)
    capsule(conn, "h1")
    [row] = compare(conn)["rows"]
    on = row["jit_on"]
    assert on["sources"] == {"hermes": 1}
    assert on["metrics"]["turns_per_session"] == {"median": None, "n": 0}
    assert on["metrics"]["tokens_per_turn"] == {"median": None, "n": 0}
    assert on["metrics"]["cache_read_share"]["median"] == pytest.approx(0.75)


def test_project_and_since_filters_and_unregistered_paths(conn):
    claude_day(conn, "a", day=DAY)
    claude_day(conn, "b", day=OTHER_DAY, path="/elsewhere/beta")
    result = compare(conn, since=OTHER_DAY)
    assert [(r["project"], r["registered"]) for r in result["rows"]] == [("/elsewhere/beta", False)]
    assert compare(conn, project="alpha")["rows"][0]["day"] == DAY


def test_report_prints_labels_n_and_missing_values(conn):
    claude_day(conn, "s1")
    capsule(conn, "s1")
    text = jit_compare_report.render(compare(conn), {"hermes": ["boom"]})
    assert "obserwacja, nie eksperyment" in text and "za mało danych" in text
    assert "n=1" in text and "n=0" in text and "brak danych" in text and "! hermes" in text


def test_cli_compare_json(tmp_path, monkeypatch, capsys):
    from hub import cli

    for name, sub in (("HOME", "home"), ("JIT_HUB_DIR", "hub"), ("HERMES_HOME", "hermes"),
                      ("JIT_CLAUDE_PROJECTS_DIR", "claude"), ("JIT_STATE_DIR", "state")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    today = date.today().isoformat()
    connection = store.connect()
    with connection:
        claude_day(connection, "s1", day=today, path="/work/unregistered")
        capsule(connection, "s1", day=today)
    connection.close()
    assert cli.main(argparse.Namespace(hub_action="compare", days=7, project=None, json=True)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["label"] == "obserwacja, nie eksperyment"
    [row] = result["rows"]
    assert row["day"] == today and row["jit_on"]["n"] == 1 and row["warning"] == "za mało danych"
