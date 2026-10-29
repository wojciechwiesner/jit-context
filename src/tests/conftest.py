import sqlite3
import sys
from pathlib import Path

import pytest

plugin_root = Path(__file__).resolve().parent.parent
if str(plugin_root) not in sys.path:
    sys.path.insert(0, str(plugin_root))

import config
from l0.db import _init_db_conn

# Real locations captured before any test can patch them. Tests must never write here.
REAL_VAULT_DIR = Path(config.VAULT_DIR)


def _module_path_attributes():
    """(module, attribute, kind) for every module-level copy of a vault/workspace path.

    `from config import VAULT_DIR` creates a copy, so patching `config` alone is not
    enough: each importing module has to be redirected as well.
    """
    import hooks
    import init
    from context import project_scan
    from l1 import project_cache

    return [
        (config, "VAULT_DIR", "vault"),
        (config, "PROJECTS_DIR", "projects"),
        (config, "WORKSPACE_DIR", "workspace"),
        (hooks, "VAULT_DIR", "vault"),
        (hooks, "WORKSPACE_DIR", "workspace"),
        (project_cache, "VAULT_DIR", "vault"),
        (project_cache, "PROJECTS_DIR", "projects"),
        (project_cache, "WORKSPACE_DIR", "workspace"),
        (project_scan, "OBSIDIAN_PROJECTS_DIR", "projects"),
        (init, "OBSIDIAN_VAULT", "vault"),
        (init, "OBSIDIAN_PROJECTS_DIR", "projects"),
        (init, "OBSIDIAN_KNOWHOW_DIR", "knowhow"),
    ]


@pytest.fixture(autouse=True)
def isolated_vault_and_workspace(tmp_path_factory, monkeypatch):
    """Point every vault/workspace path at an empty temp dir for each test.

    Tests that need a populated vault or workspace still patch these paths themselves;
    their monkeypatch calls run after this fixture and win.
    """
    root = tmp_path_factory.mktemp("isolated_home")
    targets = {
        "vault": root / "vault",
        "projects": root / "vault" / "projects",
        "knowhow": root / "vault" / "knowhow",
        "workspace": root / "workspace",
    }
    for path in targets.values():
        path.mkdir(parents=True, exist_ok=True)
    for module, attribute, kind in _module_path_attributes():
        monkeypatch.setattr(module, attribute, targets[kind], raising=False)
    yield targets


def _real_projects_snapshot(directory: Path) -> dict:
    if not directory.is_dir():
        return {}
    return {p: p.stat().st_mtime_ns for p in directory.glob("*.md")}


@pytest.fixture(autouse=True, scope="session")
def guard_real_vault_untouched(tmp_path_factory):
    """Fail the run if a test wrote into the real Obsidian projects dir (regression 2026-10-29).

    Live Hermes sessions legitimately update real dossiers while tests run, so a changed
    mtime alone is not proof. A test write is recognised by the pytest temp path it leaves
    behind (capsule URIs, session dirs) in the changed file.
    """
    real_projects = REAL_VAULT_DIR / "projects"
    pytest_temp_marker = str(tmp_path_factory.getbasetemp().parent)
    before = _real_projects_snapshot(real_projects)
    yield
    after = _real_projects_snapshot(real_projects)
    changed = [p for p in after if before.get(p) != after[p]]
    polluted = sorted(
        str(p) for p in changed if pytest_temp_marker in p.read_text(encoding="utf-8", errors="ignore")
    )
    assert not polluted, f"tests wrote into the real Obsidian vault: {polluted}"


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    _init_db_conn(conn)
    yield conn
    conn.close()
