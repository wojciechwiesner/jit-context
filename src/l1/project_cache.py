"""L1 Project Context Cache using stat() mtime_ns check (<1ms hit, <10ms reload)."""

import os
import hashlib
from typing import Dict, Optional
from pathlib import Path
from config import PROJECTS_DIR, VAULT_DIR, WORKSPACE_DIR

class ProjectCacheEntry:
    def __init__(self, path: Path, mtime_ns: int, size: int, content: str, sha256_hash: str):
        self.path = path
        self.mtime_ns = mtime_ns
        self.size = size
        self.content = content
        self.sha256_hash = sha256_hash

_CACHE: Dict[str, ProjectCacheEntry] = {}

def get_project_context(project_name: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Retrieves project context from Obsidian Vault or local repo (.planning/STATE.md)."""
    target_file = None
    cwd = Path.cwd()
    resolved_name = project_name if project_name and project_name not in ["hermes", "active", "general"] else cwd.name

    # 1. First Priority: Vault documentation
    vault_base = base_dir or PROJECTS_DIR
    candidates = [
        VAULT_DIR / "context" / "projects" / f"{resolved_name}.md",
        vault_base / f"{resolved_name}.md",
        vault_base / resolved_name / "_state.md",
        vault_base / resolved_name / "STATE.md",
    ]
    for cand in candidates:
        if cand.exists():
            target_file = cand
            break

    # 2. Fallback: Local workspace (.planning/STATE.md or PROJECT_CONTEXT.md)
    if not target_file:
        local_candidates = [
            cwd / ".planning" / "STATE.md",
            cwd / "STATE.md",
            cwd / "docs" / "STATE.md",
            WORKSPACE_DIR / resolved_name / ".planning" / "STATE.md",
            WORKSPACE_DIR / resolved_name / "STATE.md",
        ]
        for loc in local_candidates:
            if loc.exists():
                target_file = loc
                break

    if not target_file or not target_file.exists():
        return None
            
    try:
        stat_res = target_file.stat()
        mtime_ns = stat_res.st_mtime_ns
        size = stat_res.st_size
        
        cached = _CACHE.get(project_name)
        if cached and cached.mtime_ns == mtime_ns and cached.size == size:
            return cached.content
            
        # File changed or not cached -> reload
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        _CACHE[project_name] = ProjectCacheEntry(
            path=target_file,
            mtime_ns=mtime_ns,
            size=size,
            content=content,
            sha256_hash=sha256_hash
        )
        return content
    except Exception:
        return None

def clear_cache() -> None:
    _CACHE.clear()
