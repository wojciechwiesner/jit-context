"""Unit tests for JIT Context Compaction (0.4 window threshold / ~400k tokens)."""

import pytest
import sqlite3
from pathlib import Path
from l0.db import get_db, init_db
from l0.overlay import ensure_session, get_active_overlays
from context.compactor import (
    estimate_tokens,
    estimate_contents_tokens,
    is_compaction_needed,
    compact_turn_history,
)
from config import COMPACTION_TRIGGER_TOKENS


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_compactor.db"
    init_db(db_file)
    monkeypatch.setattr("l0.db.get_db", lambda *args, **kwargs: get_db(db_file))
    conn = get_db(db_file)
    yield conn
    conn.close()


def test_estimate_tokens():
    text = "Hello world! This is a test."
    tokens = estimate_tokens(text)
    assert tokens == len(text) // 4


def test_estimate_contents_tokens():
    contents = [
        {"role": "user", "parts": [{"text": "Task question"}]},
        {"role": "model", "parts": [{"text": "Calling tool"}]},
        {"role": "user", "parts": [{"functionResponse": {"name": "python_exec", "response": {"output": "12345"}}}]}
    ]
    tokens = estimate_contents_tokens(contents)
    assert tokens > 0


def test_is_compaction_needed_below_threshold():
    contents = [
        {"role": "user", "parts": [{"text": "Task question"}]},
        {"role": "model", "parts": [{"text": "Assistant answer"}]}
    ]
    assert not is_compaction_needed(contents, threshold_tokens=400000)


def test_compact_turn_history_triggers_and_persists_l0(test_db):
    session_id = "test_compaction_session"
    ensure_session(test_db, session_id)

    # Build a simulated multi-turn conversation exceeding a small test threshold
    # (e.g. 500 tokens) to test compaction behavior deterministically
    test_threshold = 150

    turn_0 = {"role": "user", "parts": [{"text": "ORIGINAL TASK: Solve problem X with JIT capsule."}]}
    turn_1 = {"role": "model", "parts": [{"text": "Calling tool 1 to search for data."}]}
    turn_2 = {"role": "user", "parts": [{"functionResponse": {"name": "web_search", "response": {"output": "A" * 800}}}]}
    turn_3 = {"role": "model", "parts": [{"text": "Calling tool 2 to inspect python code."}]}
    turn_4 = {"role": "user", "parts": [{"functionResponse": {"name": "python_exec", "response": {"output": "Result is 42\nDetails: verified"}}}]}
    turn_5 = {"role": "model", "parts": [{"text": "Recent model reasoning turn."}]}
    turn_6 = {"role": "user", "parts": [{"functionResponse": {"name": "verify", "response": {"output": "OK"}}}]}

    contents = [turn_0, turn_1, turn_2, turn_3, turn_4, turn_5, turn_6]
    orig_tokens = estimate_contents_tokens(contents)
    assert orig_tokens >= test_threshold

    compacted, telemetry = compact_turn_history(
        contents,
        session_id=session_id,
        threshold_tokens=test_threshold,
        protect_first=1,
        protect_last=2
    )

    assert telemetry["compacted"] is True
    assert telemetry["orig_tokens"] == orig_tokens
    assert telemetry["new_tokens"] < orig_tokens
    assert telemetry["reduction_pct"] > 0.0

    # Invariant I1: First turn is strictly preserved
    assert compacted[0] == turn_0
    assert "ORIGINAL TASK" in compacted[0]["parts"][0]["text"]

    # Middle turns are replaced by compaction block
    assert len(compacted) == 1 + 1 + 2  # first (1) + compacted_block (1) + recent (2) = 4
    compaction_block = compacted[1]
    assert compaction_block["role"] == "user"
    assert "[JIT CONTEXT COMPACTION" in compaction_block["parts"][0]["text"]
    assert "[python_exec]" in compaction_block["parts"][0]["text"]

    # Recent turns are preserved
    assert compacted[2] == turn_5
    assert compacted[3] == turn_6

    # Verify event was recorded to L0 SQLite WAL
    overlays = get_active_overlays(test_db, session_id)
    compaction_events = [o for o in overlays if o.get("key") == "context_compaction_0.4"]
    assert len(compaction_events) >= 1
    assert "->" in compaction_events[0]["value"]
