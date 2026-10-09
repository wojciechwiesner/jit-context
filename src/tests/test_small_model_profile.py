"""Small-model capsule profile and per-profile plugin install."""
from pathlib import Path

from context import small_model
from installer import hermes as hermes_installer

CATALOG = [
    ("systematic-debugging", "Use when encountering any bug, test failure, or unexpected behavior"),
    ("sso-access-management", "Use when managing SSO/OIDC user access or auth proxies"),
    ("pokemon-player", "Play Pokemon via headless emulator"),
]
CAPSULE = "<ONA_CONTEXT scope=\"x\">\n  [CURRENT]\n    • Goal: fix\n" + ("  filler line\n" * 400) + "</ONA_CONTEXT>"


def test_small_model_detection():
    for name in ("lfm2.5:2.6b-64k", "qwen2.5-coder:7b", "qwen3.8:jit", "qwen3.8:9b-64k", "gemma4:12b"):
        assert small_model.is_small_model(name), name
    for name in ("claude-opus-5.5", "gemini-3.8-flash", "gpt-6-luna-900k", "", None):
        assert not small_model.is_small_model(name), name


def test_skill_pointers_ranked_by_goal():
    pointers = small_model.rank_skill_pointers("debug failing test in sso proxy", CATALOG)
    names = [name for name, _ in pointers]
    assert names[:2] == ["sso-access-management", "systematic-debugging"] or set(names[:2]) == {"sso-access-management", "systematic-debugging"}
    assert "pokemon-player" not in names


def test_small_profile_caps_capsule_and_keeps_closing_tag():
    capsule, meta = small_model.apply_small_model_profile(CAPSULE, "debug sso auth", "lfm2.5:2.6b-64k", CATALOG)
    assert meta["small_model"] is True
    assert len(capsule) <= small_model.SMALL_CAPSULE_CHAR_CAP
    assert capsule.rstrip().endswith("</ONA_CONTEXT>")
    assert "[SKILL POINTERS" in capsule and "sso-access-management" in capsule


def test_large_model_capsule_untouched():
    capsule, meta = small_model.apply_small_model_profile(CAPSULE, "debug sso", "claude-opus-5.5", CATALOG)
    assert capsule == CAPSULE and meta == {"small_model": False}


def test_installer_links_only_profiles_that_enable_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes_installer, "home", lambda: tmp_path)
    profiles = tmp_path / ".hermes" / "profiles"
    (profiles / "small").mkdir(parents=True)
    (profiles / "small" / "config.yaml").write_text("plugins:\n  enabled: [ona-context]\n")
    (profiles / "listed").mkdir()
    (profiles / "listed" / "config.yaml").write_text("plugins:\n  enabled:\n    - basic\n    - ona-context\n")
    (profiles / "other").mkdir()
    (profiles / "other" / "config.yaml").write_text("plugins:\n  enabled: [basic]\n")
    links = [Path(p) for p in hermes_installer.plugin_links()]
    names = {p.parent.parent.name for p in links}
    assert names == {".hermes", "small", "listed"}


def test_small_brief_injected_from_session_cwd(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".planning").mkdir()
    (tmp_path / ".planning" / "CONTEXT_SMALL.md").write_text("# demo — small-model brief\nVerify: `pytest`\n")
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    capsule, _ = small_model.apply_small_model_profile(CAPSULE, "fix", "qwen2.5-coder:7b", CATALOG, session_cwd=str(nested))
    assert "[PROJECT BRIEF" in capsule and "Verify: `pytest`" in capsule
    assert len(capsule) <= small_model.SMALL_CAPSULE_CHAR_CAP


def test_jit_init_small_profile_writes_brief_and_profile(tmp_path):
    import json
    import small_context
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / ".planning").mkdir()
    (tmp_path / ".planning" / "STATE.md").write_text("# State\n## Current focus\nPhase 2: wire small workers\n## Other\nx\n")
    res = small_context.write_small_profile(tmp_path, {"languages": ["Python"], "frameworks": [], "entrypoints": ["src/main.py"]}, "demo goal")
    brief = (tmp_path / ".planning" / "CONTEXT_SMALL.md").read_text()
    assert len(brief) <= small_context.SMALL_BRIEF_CHAR_CAP
    assert "python3 -m pytest -q" in brief and "Phase 2: wire small workers" in brief and "src/" in brief
    profile = json.loads((tmp_path / ".planning" / "jit.json").read_text())
    assert profile["small"]["model"] == small_context.DEFAULT_SMALL_MODEL
    assert int(res["brief_chars"]) == len(brief.encode())
