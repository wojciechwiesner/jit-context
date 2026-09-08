"""L1 Project Context Cache using stat() mtime_ns check (<1ms hit, <10ms reload)."""

import os
import re
import hashlib
from typing import Dict, Optional, List
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

def normalize_project_name(name: str) -> str:
    """Normalize human or scope project name to disk/vault naming conventions."""
    if not name:
        return "general"
    n = name.lower().strip()
    n = re.sub(r"[_\s]+", "-", n)
    aliases = {
        "hermes-jit-context-os": "hermes-jit-context-os-v0.1",
        "jit-context": "hermes-jit-context-os-v0.1",
        "jit": "hermes-jit-context-os-v0.1",
        "hermes": "hermes-jit-context-os-v0.1",
    }
    return aliases.get(n, n)

def get_project_context(
    project_name: str, 
    base_dir: Optional[Path] = None,
    session_cwd: Optional[str] = None
) -> Optional[str]:
    """Retrieves project context from Obsidian Vault or local repo (.planning/STATE.md).
    
    Guaranteed scope-safe: Never injects an unrelated project's STATE.md.
    """
    target_file: Optional[Path] = None
    cwd = Path(session_cwd) if session_cwd and Path(session_cwd).exists() else Path.cwd()
    norm_name = normalize_project_name(project_name)
    raw_name = project_name.strip() if project_name else ""

    # If scope is general or unknown, do not guess or bleed arbitrary project state
    if norm_name in ("general", "unknown") and not raw_name:
        return None

    # 1. First Priority: Vault documentation (SSOT)
    vault_base = base_dir or PROJECTS_DIR
    candidates: List[Path] = [
        VAULT_DIR / "projects" / f"{norm_name}.md",
        VAULT_DIR / "context" / "projects" / f"{norm_name}.md",
        vault_base / f"{norm_name}.md",
        vault_base / f"{raw_name}.md",
        vault_base / norm_name / "_state.md",
        vault_base / norm_name / "STATE.md",
        VAULT_DIR / "projects" / f"{raw_name}.md",
        VAULT_DIR / "context" / "projects" / f"{raw_name}.md",
    ]
    for cand in candidates:
        try:
            resolved = cand.resolve()
            # Prevent path traversal outside allowed vault or project directories
            allowed_roots = [VAULT_DIR.resolve(), vault_base.resolve()]
            if not any(resolved.is_relative_to(root) for root in allowed_roots):
                continue
            if resolved.exists() and resolved.is_file():
                target_file = resolved
                break
        except (ValueError, RuntimeError):
            continue

    # 2. Local workspace (.planning/STATE.md or STATE.md)
    if not target_file:
        # Check explicit workspace path for this specific project
        workspace_candidates: List[Path] = [
            WORKSPACE_DIR / norm_name / ".planning" / "STATE.md",
            WORKSPACE_DIR / norm_name / "STATE.md",
            WORKSPACE_DIR / raw_name / ".planning" / "STATE.md",
            WORKSPACE_DIR / raw_name / "STATE.md",
            WORKSPACE_DIR / f"{raw_name}-v0.1" / ".planning" / "STATE.md",
        ]
        for w_cand in workspace_candidates:
            if w_cand.exists() and w_cand.is_file():
                target_file = w_cand
                break

    # 3. If still not found, check cwd ONLY if cwd explicitly matches project name or alias
    if not target_file:
        cwd_norm = normalize_project_name(cwd.name)
        if norm_name not in ("general", "unknown") and (cwd_norm == norm_name or cwd.name == raw_name):
            local_candidates = [
                cwd / ".planning" / "STATE.md",
                cwd / "STATE.md",
                cwd / "docs" / "STATE.md",
            ]
            for loc in local_candidates:
                if loc.exists() and loc.is_file():
                    target_file = loc
                    break

    if not target_file or not target_file.exists():
        return None
            
    try:
        stat_res = target_file.stat()
        mtime_ns = stat_res.st_mtime_ns
        size = stat_res.st_size
        
        cache_key = f"{norm_name}_{target_file}"
        cached = _CACHE.get(cache_key)
        if cached and cached.mtime_ns == mtime_ns and cached.size == size:
            return cached.content
            
        # File changed or not cached -> reload
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        _CACHE[cache_key] = ProjectCacheEntry(
            path=target_file,
            mtime_ns=mtime_ns,
            size=size,
            content=content,
            sha256_hash=sha256_hash
        )
        return content
    except Exception as e:
        print(f"[project_cache:error] Failed reading {target_file}: {e}")
        return None

def clear_project_cache():
    """Clear in-memory project context cache."""
    _CACHE.clear()
