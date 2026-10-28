"""Project scanner for `jit init` and `jit skills`: detect stack and structure, name the Obsidian dossier.

Leaf module (only depends on context.stack_signals), so init.py and skills_cli.py can both use it without
importing each other.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from context.stack_signals import (
    DEFAULT_PACKAGE_MANAGER, SKIP_DIRS, classify_python, detect_node_builtin_databases,
    detect_package_manager, knowledge_for_stack, node_test_command, parse_node_package,
)

OBSIDIAN_PROJECTS_DIR = Path.home() / "Documents/Wojciech/projects"

# Must stay in lockstep with l1.project_cache.normalize_project_name.
# Do not strip a trailing -vN: runtime looks up the directory name first.
_DOSSIER_ALIASES = {
    "hermes-jit-context-os": "hermes-jit-context-os-v0.1",
    "jit-context": "hermes-jit-context-os-v0.1",
    "jit": "hermes-jit-context-os-v0.1",
    "hermes": "hermes-jit-context-os-v0.1",
}

def dossier_stem(raw_name: str) -> str:
    """Canonical Obsidian stem. Same rules as runtime lookup, no version strip."""
    n = (raw_name or "").lower().strip()
    n = re.sub(r"[_\s]+", "-", n)
    return _DOSSIER_ALIASES.get(n, n) or "general"


def legacy_dossier_stem(raw_name: str) -> str:
    """Old init wrote this stem. Used only to avoid shadowing an existing note."""
    return re.sub(r"-v\d+(?:\.\d+)*$", "", raw_name or "")

def resolve_dossier(raw_name: str, projects_dir: Optional[Path] = None) -> Tuple[Path, bool]:
    """Pick the dossier path. True means the file already exists and must be kept."""
    projects_dir = projects_dir or OBSIDIAN_PROJECTS_DIR
    canonical = projects_dir / f"{dossier_stem(raw_name)}.md"
    if canonical.exists():
        return canonical, True
    legacy_stem = legacy_dossier_stem(raw_name)
    legacy = projects_dir / f"{legacy_stem}.md"
    if legacy_stem and legacy_stem != canonical.stem and legacy.exists():
        return legacy, True
    return canonical, False

class ProjectScanner:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir.resolve()
        self.name = dossier_stem(self.target_dir.name)

    def detect_stack(self) -> Dict[str, Any]:
        stack = {
            "languages": [],
            "helper_languages": [],
            "frameworks": [],
            "databases": [],
            "package_managers": [],
            "package_manager": None,
            "test_command": None,
            "libraries": [],
            "test_runners": [],
            "entrypoints": []
        }

        # Check Node / JS / TS (root + first-level subdirs, e.g. site/, web/)
        pkg_jsons = [self.target_dir / "package.json"] + sorted(
            d / "package.json" for d in self.target_dir.iterdir()
            if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
        )
        for pkg_json in (p for p in pkg_jsons if p.exists()):
            manager = detect_package_manager(pkg_json.parent)
            stack["package_manager"] = stack["package_manager"] or manager
            stack["test_command"] = stack["test_command"] or node_test_command(pkg_json.parent)
            node = parse_node_package(pkg_json)
            stack["languages"].append(node["language"])
            for key in ("frameworks", "databases", "test_runners", "libraries"):
                stack[key].extend(node[key])
        if stack["package_manager"] or any(p.exists() for p in pkg_jsons):
            stack["package_managers"].append(stack["package_manager"] or DEFAULT_PACKAGE_MANAGER)
            stack["databases"].extend(detect_node_builtin_databases(self.target_dir))

        # Check Python: manifest or a meaningful share of product code, not helper scripts
        python = classify_python(self.target_dir)
        if python["helper_only"]:
            stack["helper_languages"].append("Python")
        if python["primary"]:
            stack["languages"].append("Python")
            content = ""
            for manifest in ["pyproject.toml", "setup.py", "Pipfile", *sorted(p.name for p in self.target_dir.glob("requirements*.txt"))]:
                mf = self.target_dir / manifest
                if mf.exists(): content += mf.read_text(encoding="utf-8", errors="ignore")
            for pyf in python["files"]:
                content += pyf.read_text(encoding="utf-8", errors="ignore")[:500] + "\n"
            content = content.lower()
            if "fastapi" in content: stack["frameworks"].append("FastAPI")
            if "flask" in content: stack["frameworks"].append("Flask")
            if "django" in content: stack["frameworks"].append("Django")
            if "sqlite" in content: stack["databases"].append("SQLite WAL")
            if "sqlmodel" in content: stack["databases"].append("SQLModel")
            if "sqlalchemy" in content: stack["databases"].append("SQLAlchemy")
            if "asyncpg" in content: stack["databases"].append("asyncpg (PostgreSQL)")
            if "pydantic" in content: stack["libraries"].append("Pydantic")
            if "pytest" in content: stack["test_runners"].append("pytest")

        # Check Rust
        cargo = self.target_dir / "Cargo.toml"
        if cargo.exists():
            stack["languages"].append("Rust")
            stack["package_managers"].append("cargo")

        # Check Docker
        if (self.target_dir / "Dockerfile").exists() or (self.target_dir / "docker-compose.yml").exists():
            stack["frameworks"].append("Docker")

        # Deduplicate
        for k, v in stack.items():
            if isinstance(v, list):
                stack[k] = sorted(set(v))
        return stack

    def inspect_structure(self) -> Dict[str, Any]:
        key_dirs = []
        for item in self.target_dir.iterdir():
            if item.is_dir() and not item.name.startswith((".", "node_modules", "venv", "__pycache__", "dist", "build")):
                key_dirs.append(item.name)

        # Look for existing configs & documentation
        docs = []
        for f in ["README.md", "CHANGELOG.md", "STATE.md", "ARCHITECTURE.md", "PROJECT_MANIFEST.md", "CLAUDE.local.md"]:
            p = self.target_dir / f
            if p.exists(): docs.append(f)
            p_sub = self.target_dir / ".planning" / f
            if p_sub.exists(): docs.append(f".planning/{f}")

        # Look for env templates
        env_files = [f.name for f in self.target_dir.glob(".env*") if not f.name.endswith(".backup")]

        return {
            "key_dirs": sorted(key_dirs),
            "docs": sorted(docs),
            "env_files": sorted(env_files)
        }

    def infer_required_external_knowledge(self, stack: Dict[str, Any]) -> List[Dict[str, str]]:
        return knowledge_for_stack(stack)
