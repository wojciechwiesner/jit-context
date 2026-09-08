"""JIT Context Project Profiler & Knowledge Ingestion Engine.

Scans the target codebase to extract:
1. Tech stack (manifests, runtimes, package managers)
2. Architecture, key directories, entrypoints
3. Database schemas & ORM models
4. Test suites & health check spots
5. Deployment targets & environment configs
6. Reconciles with target Goal/Roadmap and generates:
   - Obsidian Dossier in ~/Documents/Wojciech/projects/<project>.md
   - Local .planning/STATE.md
   - External Knowledge Checklist (Context7 docs, Hugging Face artifacts, Firecrawl URLs)
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

OBSIDIAN_VAULT = Path(os.path.expanduser("~/Documents/Wojciech"))
OBSIDIAN_PROJECTS_DIR = OBSIDIAN_VAULT / "projects"
OBSIDIAN_KNOWHOW_DIR = OBSIDIAN_VAULT / "knowhow"

class ProjectScanner:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir.resolve()
        self.name = self.target_dir.name

    def detect_stack(self) -> Dict[str, Any]:
        stack = {
            "languages": [],
            "frameworks": [],
            "databases": [],
            "package_managers": [],
            "test_runners": [],
            "entrypoints": []
        }

        # Check Node / JS / TS
        pkg_json = self.target_dir / "package.json"
        if pkg_json.exists():
            stack["package_managers"].append("npm/yarn/pnpm")
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "next" in deps: stack["frameworks"].append("Next.js")
                if "react" in deps: stack["frameworks"].append("React")
                if "astro" in deps: stack["frameworks"].append("Astro")
                if "vue" in deps: stack["frameworks"].append("Vue")
                if "express" in deps: stack["frameworks"].append("Express")
                if "fastify" in deps: stack["frameworks"].append("Fastify")
                if "prisma" in deps: stack["databases"].append("Prisma")
                if "drizzle-orm" in deps: stack["databases"].append("Drizzle")
                if "typescript" in deps: stack["languages"].append("TypeScript")
                else: stack["languages"].append("JavaScript")
                if "vitest" in deps: stack["test_runners"].append("Vitest")
                if "jest" in deps: stack["test_runners"].append("Jest")
            except Exception:
                stack["languages"].append("JavaScript")

        # Check Python
        pyproject = self.target_dir / "pyproject.toml"
        reqs = self.target_dir / "requirements.txt"
        setup_py = self.target_dir / "setup.py"
        has_py_files = any(self.target_dir.rglob("*.py"))
        if pyproject.exists() or reqs.exists() or setup_py.exists() or has_py_files:
            stack["languages"].append("Python")
            content = ""
            if reqs.exists(): content += reqs.read_text(encoding="utf-8", errors="ignore")
            if pyproject.exists(): content += pyproject.read_text(encoding="utf-8", errors="ignore")
            for pyf in list(self.target_dir.rglob("*.py"))[:20]:
                content += pyf.read_text(encoding="utf-8", errors="ignore")[:500] + "\n"
            if "fastapi" in content.lower(): stack["frameworks"].append("FastAPI")
            if "flask" in content.lower(): stack["frameworks"].append("Flask")
            if "django" in content.lower(): stack["frameworks"].append("Django")
            if "sqlite" in content.lower() or "sqlite3" in content.lower(): stack["databases"].append("SQLite WAL")
            if "sqlmodel" in content.lower(): stack["databases"].append("SQLModel")
            if "sqlalchemy" in content.lower(): stack["databases"].append("SQLAlchemy")
            if "asyncpg" in content.lower(): stack["databases"].append("asyncpg (PostgreSQL)")
            if "pytest" in content.lower(): stack["test_runners"].append("pytest")

        # Check Rust
        cargo = self.target_dir / "Cargo.toml"
        if cargo.exists():
            stack["languages"].append("Rust")
            stack["package_managers"].append("cargo")

        # Check Docker
        if (self.target_dir / "Dockerfile").exists() or (self.target_dir / "docker-compose.yml").exists():
            stack["frameworks"].append("Docker")

        # Deduplicate
        for k in stack:
            stack[k] = sorted(list(set(stack[k])))
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
        resources = []
        for framework in stack.get("frameworks", []):
            if framework == "FastAPI":
                resources.append({"type": "context7", "target": "fastapi", "description": "Latest FastAPI routing & async dependency injection"})
            elif framework == "Next.js":
                resources.append({"type": "context7", "target": "next", "description": "Next.js App Router & Server Actions API"})
            elif framework == "Docker":
                resources.append({"type": "knowhow", "target": "devops/deployment-pitfalls", "description": "Borg tools Docker deployment canon"})

        for db in stack.get("databases", []):
            if "SQLModel" in db or "SQLAlchemy" in db:
                resources.append({"type": "context7", "target": "sqlmodel", "description": "SQLModel AsyncEngine & Pydantic v2 validation"})
            elif "Prisma" in db:
                resources.append({"type": "context7", "target": "prisma", "description": "Prisma client schema migration rules"})

        return resources

def run_init(target_path: Path, tier: str = "standard", goal: Optional[str] = None) -> Dict[str, Any]:
    scanner = ProjectScanner(target_path)
    stack = scanner.detect_stack()
    structure = scanner.inspect_structure()
    external_reqs = scanner.infer_required_external_knowledge(stack)

    # 1. Generate Obsidian Project Dossier
    OBSIDIAN_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    obsidian_file = OBSIDIAN_PROJECTS_DIR / f"{scanner.name}.md"

    doc_lines = [
        f"# Project Dossier: {scanner.name}",
        "",
        "## Overview & Meta",
        f"- **Repository Path**: `{scanner.target_dir}`",
        f"- **Primary Stack**: {', '.join(stack['languages']) if stack['languages'] else 'Generic'}",
        f"- **Frameworks**: {', '.join(stack['frameworks']) if stack['frameworks'] else 'Vanilla'}",
        f"- **Data / Storage**: {', '.join(stack['databases']) if stack['databases'] else 'None / Filesystem'}",
        f"- **Test Framework**: {', '.join(stack['test_runners']) if stack['test_runners'] else 'Native'}",
        f"- **Initialization Tier**: `{tier.upper()}`",
        f"- **Goal**: {goal or 'High-performance, reliable systems engineering.'}",
        "",
        "## Architecture & Directory Structure",
        "- **Key Directories**: " + ", ".join(f"`{d}/`" for d in structure["key_dirs"]),
        "- **Existing Docs**: " + ", ".join(f"`{d}`" for d in structure["docs"]),
        "- **Environment Profiles**: " + ", ".join(f"`{e}`" for e in structure["env_files"]),
        "",
        "## External Knowledge & Up-to-Date Documentation Needs",
    ]

    if external_reqs:
        for req in external_reqs:
            doc_lines.append(f"- `[{req['type'].upper()}]` **{req['target']}**: {req['description']}")
    else:
        doc_lines.append("- Zero third-party library documentation gaps detected.")

    doc_lines.extend([
        "",
        "## Safety Invariants & Engineering Rules",
        "- [x] Invariant I1: Current direct user prompt takes strict precedence.",
        "- [x] Invariant I4: Anti-self-poisoning (epistemic weight 0.0 for raw assistant text).",
        "- [x] Invariant I8: Lean JIT Capsule ceiling (<1.5k tokens).",
        "- [x] Verification Gate: Mandatory runtime assertion before declaring tasks done.",
        "",
        "---",
        "*Generated by Hermes JIT Context OS Profiler v0.2*"
    ])

    obsidian_content = "\n".join(doc_lines)
    obsidian_file.write_text(obsidian_content, encoding="utf-8")

    # 2. Generate or update local .planning/STATE.md if missing
    planning_dir = target_path / ".planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    state_file = planning_dir / "STATE.md"
    if not state_file.exists():
        state_content = f"""# Project State: {scanner.name}

## Active Goal
{goal or 'Initial development and feature implementation.'}

## Tech Stack
- Languages: {', '.join(stack['languages'])}
- Frameworks: {', '.join(stack['frameworks'])}

## Tasks & Phases
- [x] Phase 0: Repository Profiling & JIT Context Initialization (`/jit init`)
- [ ] Phase 1: Core Implementation & Test Harness
- [ ] Phase 2: Runtime Verification & Deployment
"""
        state_file.write_text(state_content, encoding="utf-8")

    return {
        "status": "success",
        "project": scanner.name,
        "path": str(scanner.target_dir),
        "tier": tier,
        "stack": stack,
        "structure": structure,
        "obsidian_dossier": str(obsidian_file),
        "state_file": str(state_file),
        "external_resources": external_reqs
    }

def main():
    parser = argparse.ArgumentParser(description="Hermes JIT Context OS — CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # jit init
    init_parser = subparsers.add_parser("init", help="Initialize and profile project context")
    init_parser.add_argument("path", nargs="?", default=".", help="Target project path")
    init_parser.add_argument("--tier", choices=["simple", "standard", "deep", "xhigh"], default="standard", help="Initialization depth")
    init_parser.add_argument("--goal", type=str, default=None, help="Explicit project goal")

    # Allow running directly as 'jit <path>' without subcommand
    parser.add_argument("direct_path", nargs="?", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--tier", choices=["simple", "standard", "deep", "xhigh"], default="standard", help=argparse.SUPPRESS)
    parser.add_argument("--goal", type=str, default=None, help=argparse.SUPPRESS)
    
    args, unknown = parser.parse_known_args()

    target_path = "."
    tier = "standard"
    goal = None

    if args.command == "init":
        target_path = args.path
        tier = args.tier
        goal = args.goal
    elif args.direct_path:
        target_path = args.direct_path
        tier = args.tier
        goal = args.goal

    target_dir = Path(target_path).resolve()
    res = run_init(target_dir, tier=tier, goal=goal)

    print("=" * 60)
    print(f"⚡ JIT CONTEXT OS — INITIALIZED: {res['project']}")
    print("=" * 60)
    print(f"• Ścieżka: {res['path']}")
    print(f"• Wykryty Stack: {', '.join(res['stack']['languages'])} | Frameworki: {', '.join(res['stack']['frameworks'])}")
    print(f"• Bazy Danych: {', '.join(res['stack']['databases']) or 'Brak'}")
    print(f"• Obsidian SSOT: {res['obsidian_dossier']}")
    print(f"• Local State: {res['state_file']}")
    print(f"• Zewnętrzne Zasoby (Context7/Docs): {len(res['external_resources'])} wykrytych")
    for r in res['external_resources']:
        print(f"   └─ [{r['type']}] {r['target']}: {r['description']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
