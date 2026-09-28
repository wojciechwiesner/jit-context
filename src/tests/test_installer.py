"""Host installers against a throwaway $HOME: idempotent, backups, user data preserved."""

import json

import pytest

from installer import agent_zero, claude_code, cli, hermes, opencode
from installer.common import FAIL, OK, SKIP


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("JIT_INSTALL_HOME", raising=False)
    monkeypatch.delenv("A0_DIR", raising=False)
    return tmp_path


def _commands(settings):
    return [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]


def test_hosts_are_skipped_when_absent(fake_home, monkeypatch):
    monkeypatch.setattr(opencode.shutil, "which", lambda _: None)
    monkeypatch.setattr(agent_zero, "find_containers", lambda: [])
    assert {r.status for r in cli.run("install")} == {SKIP}


def test_claude_code_install_is_idempotent_and_keeps_user_hooks(fake_home):
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    user_hook = {"type": "command", "command": "echo mine"}
    custom_jit = {"type": "command", "command": "/usr/bin/python3 /x/jit-spillover-hook.py"}
    settings_path.write_text(json.dumps({"model": "opus", "hooks": {
        "Stop": [{"hooks": [user_hook]}],
        "PostToolUse": [{"matcher": claude_code.SPILL_MATCHER, "hooks": [custom_jit]}],
    }}))

    first = claude_code.install()
    settings = json.loads(settings_path.read_text())
    assert first.status == OK and "5 settings entries added" in first.detail
    assert settings["model"] == "opus"
    assert "echo mine" in _commands(settings)
    assert sum("jit-spillover-hook.py" in c for c in _commands(settings)) == 1
    assert all((fake_home / ".claude/hooks" / n).exists() for n in claude_code.HOOK_FILES)
    assert list(settings_path.parent.glob("settings.json.bak.*"))

    assert "0 settings entries added" in claude_code.install().detail

    claude_code.uninstall()
    settings = json.loads(settings_path.read_text())
    assert _commands(settings) == ["echo mine"]
    assert not (fake_home / ".claude/hooks/jit-context-hook.py").exists()


def test_hermes_links_snapshot_and_moves_real_dir_aside(fake_home, monkeypatch):
    monkeypatch.setattr(hermes, "_hermes", lambda *args: False)
    old_dir = fake_home / ".hermes" / "plugins" / "ona-context"
    old_dir.mkdir(parents=True)
    (old_dir / "keep.txt").write_text("x")

    result = hermes.install()
    link = fake_home / ".hermes/plugins/ona-context"
    assert result.status == OK
    assert link.is_symlink() and (link / "plugin.yaml").exists()
    assert (link / "DEPLOYED_FROM.txt").exists() and not (link / "tests").exists()
    assert list(link.parent.glob("ona-context.bak.*/keep.txt"))
    assert hermes.install().status == OK  # re-run reuses the snapshot

    hermes.uninstall()
    assert not link.exists() and list((fake_home / ".hermes/plugin-releases").iterdir())


def test_opencode_npm_entry_is_added_once_and_removed(fake_home, monkeypatch):
    monkeypatch.setattr(opencode, "npm_published", lambda: True)
    cfg_path = fake_home / ".config/opencode/opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"mcp": {"a": {}}, "plugin": ["other@1.0"]}))

    assert opencode.install().status == OK
    assert opencode.install().status == OK
    cfg = json.loads(cfg_path.read_text())
    assert cfg["plugin"] == ["other@1.0", opencode.NPM_NAME] and cfg["mcp"] == {"a": {}}

    opencode.uninstall()
    assert json.loads(cfg_path.read_text())["plugin"] == ["other@1.0"]


def test_agent_zero_reinstall_keeps_plugin_data(fake_home, monkeypatch):
    monkeypatch.setattr(agent_zero, "find_containers", lambda: [])
    root = fake_home / "Projects" / "active" / "agent-zero"
    (root / "plugins" / "_plugin_installer").mkdir(parents=True)
    (root / "usr" / "plugins").mkdir(parents=True)

    assert agent_zero.install().status == OK
    target = root / "usr/plugins" / agent_zero.PLUGIN_NAME
    assert (target / "plugin.yaml").exists() and not (target / "tests").exists()
    (target / "data" / "api_key").write_text("keep-me")

    assert agent_zero.install().status == OK
    assert (target / "data" / "api_key").read_text() == "keep-me"
    assert (target / "data" / "jit_context.db").exists()  # plugin self-test ran


def test_one_failing_host_does_not_stop_the_rest(fake_home, monkeypatch):
    def boom(dry_run=False):
        raise RuntimeError("broken")

    monkeypatch.setattr(hermes, "install", boom)
    results = {r.host: r.status for r in cli.run("install", only="hermes,claude-code")}
    assert results == {"hermes": FAIL, "claude-code": SKIP}
