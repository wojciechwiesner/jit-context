"""L1 Project Context Cache using stat() mtime_ns check (<1ms hit, <10ms reload)."""

import os
import hashlib
from typing import Dict, Optional, Tuple
from pathlib import Path
from config import PROJECTS_DIR

class ProjectCacheEntry:
    def __init__(self, path: Path, mtime_ns: int, size: int, content: str, sha256_hash: str):
        self.path = path
        self.mtime_ns = mtime_ns
        self.size = size
        self.content = content
        self.sha256_hash = sha256_hash

_CACHE: Dict[str, ProjectCacheEntry] = {}

def get_project_context(project_name: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Retrieves project context from ~/Documents/Wojciech/projects/<name>.md with zero I/O on hit."""
    vault_dir = base_dir or PROJECTS_DIR
    target_file = vault_dir / f"{project_name}.md"
    
    if not target_file.exists():
        # Try finding canonical entry point
        alt_file = vault_dir / project_name / "_state.md"
        if alt_file.exists():
            target_file = alt_file
        else:
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
