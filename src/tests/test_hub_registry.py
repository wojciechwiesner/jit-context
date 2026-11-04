"""Project Hub registry: worktrees map to the main repo, scans are idempotent, corrupt files are rebuilt."""

import json
import subprocess
import sys
from pathlib import Path

import config
import init as init_mod
from hub import registry
from hub.gitinfo import resolve_repo
from hub.scan import scan

INIT_PY = Path(init_mod.__file__).resolve()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def make_repo(path: Path, marker: str = "STATE.md") -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    if marker:
        (path / ".planning").mkdir()
        (path / ".planning" / marker).write_text("# State\n", encoding="utf-8")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


def add_worktree(repo: Path, target: Path) -> Path:
    git(repo, "worktree", "add", "-q", "-b", "wt-" + target.name, str(target))
    return target


def test_registry_path_follows_env(isolated_hub_dir):
    assert registry.registry_path() == isolated_hub_dir / registry.REGISTRY_FILE_NAME
    assert config.hub_dir() == isolated_hub_dir


def test_worktree_resolves_to_main_entry(tmp_path):
    main = make_repo(tmp_path / "Alpha Repo")
    worktree = add_worktree(main, tmp_path / "alpha-wt")
    identity = resolve_repo(worktree)
    assert identity.is_worktree and identity.main_path == main.resolve()

    entry, created = registry.register_project(main, from_init=True)
    assert created and entry["slug"] == "alpha-repo"
    assert entry["git_common_dir"] == str((main / ".git").resolve())
    assert entry["last_init_at"] and entry["added_at"]

    again, created_again = registry.register_project(worktree, from_init=True)
    assert not created_again
    assert again["path"] == str(main.resolve())
    assert len(registry.load_projects()) == 1


def test_scan_skips_worktrees_and_is_idempotent(tmp_path):
    root = tmp_path / "root"
    alpha = make_repo(root / "alpha")
    make_repo(root / "group" / "beta", marker="jit.json")
    make_repo(root / "plain", marker="")
    add_worktree(alpha, root / "alpha-wt")
    (root / "node_modules" / "dep" / ".planning").mkdir(parents=True)

    first = scan(root)
    assert sorted(e["slug"] for e in first.registered) == ["alpha", "beta"]
    assert first.known == []
    assert [p.name for p in first.skipped_worktrees] == ["alpha-wt"]
    assert first.unmarked_repos == 1
    assert all(e["last_init_at"] is None for e in first.registered)
    snapshot = registry.registry_path().read_text(encoding="utf-8")

    second = scan(root)
    assert second.registered == []
    assert sorted(e["slug"] for e in second.known) == ["alpha", "beta"]
    assert registry.registry_path().read_text(encoding="utf-8") == snapshot


def test_corrupt_registry_is_backed_up_and_rebuilt(tmp_path, capsys):
    make_repo(tmp_path / "root" / "gamma")
    path = registry.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    report = scan(tmp_path / "root")
    assert [e["slug"] for e in report.registered] == ["gamma"]
    backups = list(path.parent.glob(registry.REGISTRY_FILE_NAME + registry.CORRUPT_SUFFIX + "*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{not json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == registry.REGISTRY_VERSION
    assert [e["slug"] for e in data["projects"]] == ["gamma"]
    assert "uszkodzony rejestr" in capsys.readouterr().err


def test_wrong_shape_counts_as_corrupt(tmp_path):
    path = registry.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": [{"slug": ""}]}), encoding="utf-8")
    assert registry.load_projects() == []
    assert json.loads(path.read_text(encoding="utf-8"))["projects"] == []


def test_slug_collision_gets_suffix(tmp_path):
    first, _ = registry.register_project(make_repo(tmp_path / "a" / "app"))
    second, _ = registry.register_project(make_repo(tmp_path / "b" / "app"))
    assert (first["slug"], second["slug"]) == ("app", "app-2")


def test_non_git_directory_is_registered_without_common_dir(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    entry, created = registry.register_project(folder, from_init=True)
    assert created and entry["git_common_dir"] is None and entry["path"] == str(folder.resolve())


def run_cli(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(INIT_PY), *argv], cwd=cwd, capture_output=True, text=True, timeout=60)


def test_cli_scan_and_list(tmp_path):
    root = tmp_path / "root"
    make_repo(root / "delta")
    res = run_cli("hub", "scan", str(root), cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "Nowe w rejestrze: 1" in res.stdout and "Pominięte worktree: 0" in res.stdout

    listed = run_cli("hub", "list", cwd=tmp_path)
    assert listed.returncode == 0 and "delta" in listed.stdout and "init: brak" in listed.stdout
    raw = run_cli("hub", "list", "--json", cwd=tmp_path)
    assert [e["slug"] for e in json.loads(raw.stdout)] == ["delta"]

    missing = run_cli("hub", "scan", str(tmp_path / "nope"), cwd=tmp_path)
    assert missing.returncode == 2 and "nie istnieje" in missing.stdout


def fake_run_init(target_dir, tier="standard", goal=None):
    stack = {"languages": [], "frameworks": [], "databases": []}
    return {"project": target_dir.name, "path": str(target_dir), "stack": stack, "obsidian_dossier": "-",
            "dossier_action": "preserved", "state_file": "-", "external_resources": []}


def test_jit_init_registers_main_repo_from_worktree(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path / "epsilon")
    worktree = add_worktree(repo, tmp_path / "epsilon-wt")
    monkeypatch.setattr(init_mod, "run_init", fake_run_init)
    monkeypatch.setattr(sys, "argv", ["jit", "init", str(worktree)])
    init_mod.main()
    assert "Hub: epsilon (nowy wpis)" in capsys.readouterr().out
    [entry] = registry.load_projects()
    assert entry["path"] == str(repo.resolve()) and entry["last_init_at"]
