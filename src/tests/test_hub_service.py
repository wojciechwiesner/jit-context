"""Refresher launchd agent: plist written into a throwaway $HOME, never loaded unless --load (fake launchctl)."""

import argparse
import os
import plistlib
import stat
import subprocess
import sys

import pytest

from hub import cli as hub_cli
from installer import hub_refresher
from installer.common import FAIL, OK, SKIP

FAKE_LAUNCHCTL = """#!/bin/sh
echo "$@" >> "$FAKE_LAUNCHCTL_LOG"
if [ "$1" = "print" ]; then exit "${FAKE_LAUNCHCTL_PRINT_EXIT:-113}"; fi
exit 0
"""


def _executable(path, body="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake_mac(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Library").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("JIT_INSTALL_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    brew = tmp_path / "brew" / "bin"
    _executable(brew / "python3.11")
    monkeypatch.setattr(hub_refresher, "HOMEBREW_BIN_DIRS", (brew,))
    fake_bin = tmp_path / "fakebin"
    _executable(fake_bin / "launchctl", FAKE_LAUNCHCTL)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "launchctl.log"
    monkeypatch.setenv("FAKE_LAUNCHCTL_LOG", str(log))
    return {"home": home, "brew": brew, "launchctl_log": log}


def _service_args(load=False):
    return argparse.Namespace(hub_action="install-service", load=load)


def test_install_writes_a_valid_plist_and_loads_nothing(fake_mac):
    result = hub_refresher.install()
    assert result.status == OK, result.detail
    plist_file = fake_mac["home"] / "Library" / "LaunchAgents" / "io.theones.jit-hub-refresher.plist"
    with plist_file.open("rb") as handle:
        data = plistlib.load(handle)
    python = str(fake_mac["brew"] / "python3.11")
    assert data["Label"] == "io.theones.jit-hub-refresher"
    assert data["ProgramArguments"] == [python, "-m", "init", "hub", "refresh", "--interval", "60"]
    assert data["KeepAlive"] is True
    assert data["ThrottleInterval"] == 30
    log = str(fake_mac["home"] / "Library" / "Logs" / "jit-hub-refresher.log")
    assert data["StandardOutPath"] == log and data["StandardErrorPath"] == log
    workdir = data["WorkingDirectory"]
    assert workdir.startswith(str(fake_mac["home"] / ".hermes")) and "/Documents/" not in workdir
    assert (fake_mac["home"] / ".hermes" / "state" / "jit-hub" / "runtime" / "current" / "init.py").is_file()
    assert os.path.realpath(workdir) != workdir  # the stable `current` link, retargeted by every install
    assert str(fake_mac["brew"]) in data["EnvironmentVariables"]["PATH"].split(":")
    assert not fake_mac["launchctl_log"].exists()


def test_plist_command_starts_from_the_runtime_snapshot(fake_mac, tmp_path):
    assert hub_refresher.install().status == OK
    with hub_refresher.plist_path().open("rb") as handle:
        data = plistlib.load(handle)
    args = [sys.executable] + data["ProgramArguments"][1:5] + ["--once"]
    env = {**os.environ, "HOME": str(fake_mac["home"]), "JIT_HUB_DIR": str(tmp_path / "hub")}
    proc = subprocess.run(args, cwd=data["WorkingDirectory"], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "Hub refresh" in proc.stdout and "projekty 0" in proc.stdout


def test_reinstall_keeps_identical_plist(fake_mac):
    assert hub_refresher.install().status == OK
    second = hub_refresher.install()
    assert second.status == OK and "plist unchanged" in second.detail
    assert not fake_mac["launchctl_log"].exists()


def test_find_python_prefers_oldest_supported_homebrew_python(fake_mac):
    brew = fake_mac["brew"]
    _executable(brew / "python3.13")
    _executable(brew / "python3.9")
    (brew / "python3.10").write_text("not executable")
    assert hub_refresher.find_python() == brew / "python3.11"
    (brew / "python3.11").unlink()
    assert hub_refresher.find_python() == brew / "python3.13"


def test_missing_homebrew_python_is_a_failure_not_a_guess(fake_mac):
    (fake_mac["brew"] / "python3.11").unlink()
    result = hub_refresher.install()
    assert result.status == FAIL and "python3.11+" in result.detail
    assert not hub_refresher.plist_path().exists()


def test_install_is_skipped_without_library(fake_mac, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "bare-home"))
    assert hub_refresher.install().status == SKIP


def test_install_service_prints_the_command_and_does_not_load(fake_mac, capsys):
    assert hub_cli.main(_service_args()) == 0
    out = capsys.readouterr().out
    assert f"launchctl bootstrap gui/{os.getuid()} {hub_refresher.plist_path()}" in out
    assert hub_refresher.plist_path().is_file()
    assert not fake_mac["launchctl_log"].exists()


def test_install_service_load_bootstraps_the_plist(fake_mac, capsys):
    assert hub_cli.main(_service_args(load=True)) == 0
    calls = fake_mac["launchctl_log"].read_text().splitlines()
    domain = f"gui/{os.getuid()}"
    assert calls == [f"print {domain}/io.theones.jit-hub-refresher", f"bootstrap {domain} {hub_refresher.plist_path()}"]


def test_install_service_load_reloads_a_loaded_agent(fake_mac, monkeypatch):
    monkeypatch.setenv("FAKE_LAUNCHCTL_PRINT_EXIT", "0")
    assert hub_cli.main(_service_args(load=True)) == 0
    verbs = [line.split()[0] for line in fake_mac["launchctl_log"].read_text().splitlines()]
    assert verbs == ["print", "bootout", "bootstrap"]


def test_uninstall_refuses_while_loaded(fake_mac, monkeypatch):
    assert hub_refresher.install().status == OK
    monkeypatch.setenv("FAKE_LAUNCHCTL_PRINT_EXIT", "0")
    result = hub_refresher.uninstall()
    assert result.status == FAIL and "bootout" in result.detail
    assert hub_refresher.plist_path().exists()
    monkeypatch.setenv("FAKE_LAUNCHCTL_PRINT_EXIT", "113")
    assert hub_refresher.uninstall().status == OK
    assert not hub_refresher.plist_path().exists()
