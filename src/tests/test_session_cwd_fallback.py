"""Session cwd fallback: before any terminal tool runs, scope comes from Hermes' own session row."""
import sqlite3

from l0 import overlay


def _overlay_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, last_cwd TEXT, updated_at TEXT)")
    return conn


def _hermes_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT)")
    con.executemany("INSERT INTO sessions VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_falls_back_to_hermes_session_cwd(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    _hermes_db(db, [("child-1", "/repo/jit-context"), ("other", "/repo/faktury")])
    monkeypatch.setenv("HERMES_STATE_DB", str(db))
    assert overlay.get_session_cwd(_overlay_db(), "child-1") == "/repo/jit-context"


def test_overlay_cwd_wins_over_hermes_row(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    _hermes_db(db, [("s1", "/repo/a")])
    monkeypatch.setenv("HERMES_STATE_DB", str(db))
    conn = _overlay_db()
    conn.execute("INSERT INTO sessions VALUES ('s1', '/repo/b', '')")
    assert overlay.get_session_cwd(conn, "s1") == "/repo/b"


def test_unknown_session_or_missing_db_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STATE_DB", str(tmp_path / "missing.db"))
    assert overlay.get_session_cwd(_overlay_db(), "nope") is None
    db = tmp_path / "state.db"
    _hermes_db(db, [("s1", "/repo/a")])
    monkeypatch.setenv("HERMES_STATE_DB", str(db))
    assert overlay.get_session_cwd(_overlay_db(), "someone-else") is None
