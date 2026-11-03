"""Project dossier lookup: curated context card + vault note, without stale session goals."""

import pytest

from l1 import project_cache


@pytest.fixture
def vault(tmp_path, monkeypatch):
    (tmp_path / "projects").mkdir()
    (tmp_path / "context" / "projects").mkdir(parents=True)
    monkeypatch.setattr(project_cache, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(project_cache, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(project_cache, "WORKSPACE_DIR", tmp_path / "workspace")
    project_cache.clear_project_cache()
    yield tmp_path
    project_cache.clear_project_cache()


def test_curated_card_is_merged_before_vault_note(vault):
    (vault / "projects" / "shop.md").write_text("# Project Dossier: shop\n- auto-synced note\n")
    (vault / "context" / "projects" / "shop.md").write_text("# SHOP\n- Server: s1, port 8002\n")

    doc = project_cache.get_project_context("shop")

    assert doc is not None
    assert "port 8002" in doc
    assert "auto-synced note" in doc
    assert doc.index("port 8002") < doc.index("auto-synced note")


def test_curated_card_alone_is_enough(vault):
    (vault / "context" / "projects" / "shop.md").write_text("# SHOP\n- port 8002\n")

    doc = project_cache.get_project_context("shop")

    assert doc is not None
    assert doc.count("port 8002") == 1


def test_vault_note_alone_still_works(vault):
    (vault / "projects" / "shop.md").write_text("# Project Dossier: shop\n")

    assert project_cache.get_project_context("shop") == "# Project Dossier: shop\n"


def test_unknown_project_returns_none(vault):
    assert project_cache.get_project_context("nope") is None


def test_isolated_state_dir_never_writes_project_note(tmp_path, monkeypatch):
    from l1 import obsidian_sync

    note = tmp_path / "shop.md"
    note.write_text("# Project Dossier: shop\n")
    monkeypatch.setattr(obsidian_sync, "find_obsidian_project_dossier", lambda scope: note)
    monkeypatch.setenv("JIT_STATE_DIR", str(tmp_path / "state"))

    ok, _ = obsidian_sync.record_session_snapshot_to_obsidian(scope="shop", session_id="s1", goal="bench prompt")

    assert ok is False
    assert note.read_text() == "# Project Dossier: shop\n"


def test_compiler_strips_last_session_section():
    from context.compiler import LAST_SESSION_SECTION

    doc = (
        "# D\n\n## Ostatnia Sesja JIT\n- **Sesja:** `x`\n- **Cel:** old prompt\n"
        "## Overview\n- stack\n"
    )
    cleaned = LAST_SESSION_SECTION.sub("", doc)

    assert "old prompt" not in cleaned
    assert "## Overview\n- stack" in cleaned


def test_compiler_strips_last_session_section_at_end_of_note():
    from context.compiler import LAST_SESSION_SECTION

    cleaned = LAST_SESSION_SECTION.sub("", "# D\n- port 8002\n\n## Ostatnia Sesja JIT\n- **Cel:** old\n")

    assert "old" not in cleaned
    assert "port 8002" in cleaned
