"""jit init must keep an existing Obsidian dossier and match runtime lookup."""

import init as init_mod
from l1.obsidian_sync import find_obsidian_project_dossier


def test_dossier_stem_keeps_version_and_alias():
    assert init_mod.dossier_stem("hermes-jit-context-os-v0.1") == "hermes-jit-context-os-v0.1"
    assert init_mod.dossier_stem("hermes-jit-context-os") == "hermes-jit-context-os-v0.1"
    assert init_mod.dossier_stem("smart-convo-pwa") == "smart-convo-pwa"


def test_resolve_preserves_canonical_and_legacy(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(init_mod, "OBSIDIAN_PROJECTS_DIR", projects)

    canonical = projects / "hermes-jit-context-os-v0.1.md"
    canonical.write_text("HAND WRITTEN", encoding="utf-8")
    path, existed = init_mod.resolve_dossier("hermes-jit-context-os-v0.1")
    assert existed is True
    assert path == canonical

    legacy_only = tmp_path / "legacy"
    legacy_only.mkdir()
    monkeypatch.setattr(init_mod, "OBSIDIAN_PROJECTS_DIR", legacy_only)
    old = legacy_only / "foo.md"
    old.write_text("OLD NOTE", encoding="utf-8")
    path, existed = init_mod.resolve_dossier("foo-v2")
    assert existed is True
    assert path == old
    assert not (legacy_only / "foo-v2.md").exists()


def test_run_init_does_not_overwrite_dossier(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(init_mod, "OBSIDIAN_PROJECTS_DIR", projects)
    note = projects / "sample-app.md"
    note.write_text("KEEP ME", encoding="utf-8")

    target = tmp_path / "sample-app"
    target.mkdir()
    (target / "app.py").write_text("print('ok')\n", encoding="utf-8")

    first = init_mod.run_init(target, tier="standard")
    assert first["dossier_action"] == "preserved"
    assert note.read_text(encoding="utf-8") == "KEEP ME"

    second = init_mod.run_init(target, tier="standard")
    assert second["dossier_action"] == "preserved"
    assert note.read_text(encoding="utf-8") == "KEEP ME"


def test_run_init_creates_versioned_name_once(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(init_mod, "OBSIDIAN_PROJECTS_DIR", projects)
    target = tmp_path / "widget-v3"
    target.mkdir()

    created = init_mod.run_init(target, tier="standard")
    dossier = projects / "widget-v3.md"
    assert created["dossier_action"] == "created"
    assert dossier.exists()
    assert not (projects / "widget.md").exists()
    body = dossier.read_text(encoding="utf-8")

    again = init_mod.run_init(target, tier="standard")
    assert again["dossier_action"] == "preserved"
    assert dossier.read_text(encoding="utf-8") == body


def test_lookup_prefers_versioned_then_legacy(tmp_path, monkeypatch):
    import config

    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(config, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects)

    versioned = projects / "hermes-jit-context-os-v0.1.md"
    stripped = projects / "hermes-jit-context-os.md"
    versioned.write_text("CANON", encoding="utf-8")
    stripped.write_text("LEGACY", encoding="utf-8")

    found = find_obsidian_project_dossier("hermes-jit-context-os-v0.1")
    assert found == versioned

    versioned.unlink()
    found_legacy = find_obsidian_project_dossier("hermes-jit-context-os-v0.1")
    assert found_legacy == stripped
