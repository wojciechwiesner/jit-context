"""A default-profile deployment must not modify or orphan other Hermes profiles."""

import os

from installer import cli, hermes
from installer.common import OK


def test_default_only_install_preserves_other_profiles_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("JIT_INSTALL_HOME", raising=False)
    monkeypatch.setattr(hermes, "_hermes", lambda *args: False)
    root = tmp_path / ".hermes"
    releases = root / "plugin-releases"
    for index in range(5):
        old = releases / f"ona-context-old-{index}"
        old.mkdir(parents=True)
        (old / "keep.txt").write_text("existing profile snapshot")
        os.utime(old, (index + 1, index + 1))
    protected = releases / "ona-context-old-0"
    profile = root / "profiles" / "untouched"
    (profile / "plugins").mkdir(parents=True)
    settings = "plugins:\n  enabled: [ona-context]\n"
    (profile / "config.yaml").write_text(settings)
    link = profile / "plugins" / "ona-context"
    link.symlink_to(protected)

    results = cli.run("install", only="hermes", active_profile_only=True)

    assert results[0].status == OK
    assert (root / "plugins" / "ona-context" / "DEPLOYED_FROM.txt").exists()
    assert link.resolve() == protected
    assert (protected / "keep.txt").read_text() == "existing profile snapshot"
    assert (profile / "config.yaml").read_text() == settings
    assert hermes.plugin_links(include_profiles=False) == [root / "plugins" / "ona-context"]
