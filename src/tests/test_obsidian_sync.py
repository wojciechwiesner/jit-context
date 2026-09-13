"""Tests for Obsidian SSOT Synchronization Engine."""

import pytest
import os
import shutil
import tempfile
from pathlib import Path
from l1.obsidian_sync import (
    find_obsidian_project_dossier,
    sync_obsidian_on_commit,
    check_obsidian_staleness
)

@pytest.fixture
def temp_vault_and_repo(monkeypatch):
    temp_dir = Path(tempfile.mkdtemp())
    vault_dir = temp_dir / "Vault"
    projects_dir = vault_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    
    repo_dir = temp_dir / "my_project"
    repo_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize a mock git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@theones.io"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test Operator"], cwd=repo_dir, capture_output=True, check=True)
    
    test_file = repo_dir / "app.py"
    test_file.write_text("print('hello world')")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "feat: initial commit"], cwd=repo_dir, capture_output=True, check=True)
    
    # Create initial Obsidian dossier
    dossier = projects_dir / "my_project.md"
    dossier.write_text("# Projekt: my_project\n- **Stan:** Aktywny\n- **Ostatni Commit:** `old_sha initial`\n")
    
    # Monkeypatch config VAULT_DIR
    import config
    monkeypatch.setattr(config, "VAULT_DIR", vault_dir)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects_dir)
    
    yield vault_dir, repo_dir, dossier
    
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_find_obsidian_project_dossier(temp_vault_and_repo):
    vault_dir, repo_dir, dossier = temp_vault_and_repo
    found = find_obsidian_project_dossier("my_project")
    assert found is not None
    assert found.exists()
    assert found == dossier

def test_sync_obsidian_on_commit(temp_vault_and_repo):
    vault_dir, repo_dir, dossier = temp_vault_and_repo
    
    # Make a commit in repo
    test_file = repo_dir / "app.py"
    test_file.write_text("print('updated code')")
    import subprocess
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "fix(core): resolve race condition in pipeline"], cwd=repo_dir, capture_output=True, check=True)
    
    ok, msg = sync_obsidian_on_commit("my_project", str(repo_dir))
    assert ok is True
    assert "Updated Obsidian SSOT" in msg
    
    # Check dossier content
    content = dossier.read_text()
    assert "fix(core): resolve race condition in pipeline" in content
    assert "Ostatnia synchronizacja:" in content

def test_check_obsidian_staleness(temp_vault_and_repo):
    vault_dir, repo_dir, dossier = temp_vault_and_repo
    
    # Commit is not in dossier yet
    test_file = repo_dir / "app.py"
    test_file.write_text("print('stale change')")
    import subprocess
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "feat: new feature not synced"], cwd=repo_dir, capture_output=True, check=True)
    
    warning = check_obsidian_staleness("my_project", str(repo_dir))
    assert warning is not None
    assert "Obsidian SSOT desync" in warning
