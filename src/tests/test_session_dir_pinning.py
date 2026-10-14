"""scope_split: a session's storage dir must stay pinned to the scope it was created under."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from config import get_session_dir, get_session_db_path, get_session_meta_path


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setattr("config.SESSIONS_DIR", root)
    config._SESSION_DIR_CACHE.clear()
    yield root
    config._SESSION_DIR_CACHE.clear()


def _session_dirs(root, sid):
    return sorted(p for p in root.glob(f"*/{sid}") if p.is_dir())


def test_scope_change_reuses_original_dir(isolated_sessions):
    first = get_session_dir("sess_1", project="general")
    second = get_session_dir("sess_1", project="synthapse")
    assert first == second
    assert first.parent.name == "general"
    assert len(_session_dirs(isolated_sessions, "sess_1")) == 1
    assert not (isolated_sessions / "synthapse").exists()


def test_all_paths_follow_pinned_dir(isolated_sessions):
    get_session_dir("sess_2", project="general")
    assert get_session_db_path("sess_2", project="paula").parent.parent.name == "general"
    assert get_session_meta_path("sess_2", project="paula").parent.parent.name == "general"


def test_new_session_uses_its_project(isolated_sessions):
    d = get_session_dir("sess_3", project="synthapse")
    assert d == isolated_sessions / "synthapse" / "sess_3"
    assert get_session_dir("sess_3", project="general") == d


def test_different_sessions_do_not_collide(isolated_sessions):
    a = get_session_dir("sess_a", project="proj")
    b = get_session_dir("sess_b", project="proj")
    assert a != b


def test_preexisting_fork_resolves_to_oldest(isolated_sessions):
    newer = isolated_sessions / "synthapse" / "sess_4"
    older = isolated_sessions / "general" / "sess_4"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert get_session_dir("sess_4", project="synthapse") == older
    config._SESSION_DIR_CACHE.clear()
    assert get_session_dir("sess_4", project="other") == older


def test_cache_recovers_when_dir_removed(isolated_sessions):
    import shutil
    d = get_session_dir("sess_5", project="general")
    shutil.rmtree(d)
    fresh = get_session_dir("sess_5", project="synthapse")
    assert fresh == isolated_sessions / "synthapse" / "sess_5"
