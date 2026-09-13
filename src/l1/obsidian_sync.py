"""Obsidian SSOT Synchronization Engine for JIT-Context.

Guarantees Invariant: Any git commit or production deployment automatically
synchronizes the canonical project dossier in ~/Documents/Wojciech/projects/<scope>.md,
preventing desynchronization between code execution and the Obsidian Single Source of Truth.
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import config

def find_obsidian_project_dossier(scope: str) -> Optional[Path]:
    """Locate the canonical project dossier in Obsidian vault."""
    if not scope or scope in ("general", "hermes", "default"):
        return None
    
    clean_scope = scope.lower().replace("_", "-")
    vault_dir = getattr(config, "VAULT_DIR", Path.home() / "Documents" / "Wojciech")
    projects_dir = getattr(config, "PROJECTS_DIR", vault_dir / "projects")
    
    candidates = [
        projects_dir / f"{scope}.md",
        projects_dir / f"{clean_scope}.md",
        vault_dir / "projects" / f"{scope}.md",
        vault_dir / "projects" / f"{clean_scope}.md",
        vault_dir / "context" / "projects" / f"{scope}.md",
        vault_dir / "context" / "projects" / f"{clean_scope}.md",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None

def sync_obsidian_on_commit(scope: str, cwd: str, commit_sha: str = "", commit_msg: str = "") -> Tuple[bool, str]:
    """Auto-updates the Obsidian dossier header when a commit is made in the project."""
    dossier = find_obsidian_project_dossier(scope)
    if not dossier:
        return False, f"No Obsidian dossier found for scope '{scope}'"

    # If SHA is not provided, fetch from repo
    if not commit_sha:
        try:
            r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                commit_sha = r.stdout.strip()
        except Exception:
            pass

    if not commit_msg and commit_sha:
        try:
            r = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=cwd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                commit_msg = r.stdout.strip()
        except Exception:
            pass

    if not commit_sha:
        return False, "Could not determine git commit SHA"

    try:
        content = dossier.read_text(encoding="utf-8")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 1. Update or insert 'Ostatni Commit' and 'Ostatnia synchronizacja'
        sync_line = f"- **Ostatnia synchronizacja:** `{now_str}`"
        commit_entry = f"- **Ostatni Commit:** `{commit_sha}` {commit_msg}\n{sync_line}"
        if re.search(r"-\s+\*\*Ostatni Commit:\*\*.*", content):
            content = re.sub(r"-\s+\*\*Ostatni Commit:\*\*.*", commit_entry, content)
            if "- **Ostatnia synchronizacja:**" in content:
                content = re.sub(r"-\s+\*\*Ostatnia synchronizacja:\*\*.*", sync_line, content)
        else:
            header_match = re.search(r"(#\s+Projekt:[^\n]*\n)", content)
            if header_match:
                idx = header_match.end()
                content = content[:idx] + f"{commit_entry}\n" + content[idx:]
            else:
                content = f"{commit_entry}\n\n" + content

        # 2. Append to change log section if present
        if "## Historia Wdrożeń i Zmian" in content or "## Changelog" in content:
            log_line = f"- `{now_str}`: Commit `{commit_sha}` — {commit_msg}"
            if "## Historia Wdrożeń i Zmian" in content:
                content = content.replace(
                    "## Historia Wdrożeń i Zmian\n",
                    f"## Historia Wdrożeń i Zmian\n{log_line}\n"
                )
        
        dossier.write_text(content, encoding="utf-8")
        return True, f"Updated Obsidian SSOT at {dossier.name} (SHA: {commit_sha})"
    except Exception as e:
        return False, f"Error updating Obsidian dossier: {e}"

def check_obsidian_staleness(scope: str, cwd: str) -> Optional[str]:
    """Checks if the Obsidian dossier is desynchronized with local git HEAD."""
    dossier = find_obsidian_project_dossier(scope)
    if not dossier:
        return f"Brak notatki w Obsidianie (~/Documents/Wojciech/projects/{scope}.md). Utwórz dossier projektu!"

    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return None
        current_head = r.stdout.strip()
        if not current_head:
            return None

        content = dossier.read_text(encoding="utf-8")
        match = re.search(r"-\s+\*\*Ostatni Commit:\*\*\s+`?([a-zA-Z0-9_\-]+)`?", content)
        if match:
            recorded_sha = match.group(1)[:7]
            if recorded_sha != current_head[:7]:
                return f"Obsidian SSOT desync: notatka wskazuje commit {recorded_sha}, a w repozytorium jest {current_head}. Zsynchronizuj notatkę w Obsidianie!"
        else:
            return f"Obsidian SSOT desync: brak wpisu o commit SHA w notatce {dossier.name} (HEAD: {current_head})."
    except Exception:
        pass
    return None

def get_obsidian_dossier_info(scope: str, cwd: Optional[str] = None) -> dict:
    """Returns detailed status and timestamp of the Obsidian SSOT dossier."""
    dossier = find_obsidian_project_dossier(scope)
    if not dossier:
        return {
            "exists": False,
            "status": "brak notatki",
            "date_str": "",
            "is_stale": False,
            "filename": "",
        }

    date_str = ""
    try:
        content = dossier.read_text(encoding="utf-8")
        patterns = [
            r"-\s+\*\*Ostatnia synchronizacja:\*\*\s+`?([^`\n]+)`?",
            r"-\s+\*\*Ostatnia aktualizacja:\*\*\s+`?([^`\n]+)`?",
            r"-\s+\*\*Data aktualizacji:\*\*\s+`?([^`\n]+)`?",
            r"-\s+\*\*Data:\*\*\s+`?([^`\n]+)`?",
        ]
        for pat in patterns:
            m = re.search(pat, content)
            if m:
                raw_date = m.group(1).strip()
                date_str = raw_date[:16].replace("T", " ")
                break

        if not date_str:
            mtime = dossier.stat().st_mtime
            date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        date_str = "nieznana"

    is_stale = False
    if cwd:
        staleness = check_obsidian_staleness(scope, cwd)
        if staleness and "desync" in staleness.lower():
            is_stale = True

    status_label = f"zsynchronizowany (z {date_str})" if not is_stale else f"wymaga aktualizacji (z {date_str})"

    return {
        "exists": True,
        "status": status_label,
        "date_str": date_str,
        "is_stale": is_stale,
        "filename": dossier.name,
    }

