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
import re
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

OBSIDIAN_VAULT = Path(os.path.expanduser("~/Documents/Wojciech"))
OBSIDIAN_PROJECTS_DIR = OBSIDIAN_VAULT / "projects"
OBSIDIAN_KNOWHOW_DIR = OBSIDIAN_VAULT / "knowhow"

class ProjectScanner:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir.resolve()
        raw_name = self.target_dir.name
        self.name = re.sub(r"-v\d+(\.\d+)*$", "", raw_name)

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

def fetch_and_synthesize_deep_knowledge(target_dir: Path, stack: Dict[str, Any], tier: str = "deep") -> Dict[str, str]:
    """Generates authoritative, up-to-date cheat sheets and links relevant knowhow."""
    resources = {}
    
    # 1. Scan local ~/Documents/Wojciech/knowhow/ for architectural canon
    knowhow_dir = Path("/Users/wojciechwiesner/Documents/Wojciech/knowhow")
    matched_knowhow = []
    if knowhow_dir.exists():
        try:
            proj_raw = target_dir.name
            proj_parts = [p.lower() for p in re.split(r'[^a-zA-Z0-9]+', proj_raw) if len(p) > 2 and not p.startswith('v0') and not p.startswith('v1') and not p.startswith('v2')]
            for f in knowhow_dir.rglob("*.md"):
                fname = f.name.lower()
                for part in proj_parts:
                    if part in fname:
                        matched_knowhow.append(str(f))
                for lang in stack.get("languages", []):
                    if lang.lower() in fname:
                        matched_knowhow.append(str(f))
                for fw in stack.get("frameworks", []):
                    if fw.lower() in fname:
                        matched_knowhow.append(str(f))
                for db in stack.get("databases", []):
                    if db.lower().split()[0] in fname:
                        matched_knowhow.append(str(f))
        except Exception:
            pass

    if matched_knowhow:
        resources["local_knowhow"] = "\n".join(f"- `{p}`" for p in sorted(list(set(matched_knowhow))))

    # 2. Synthesize SOTA architecture reference cards for detected frameworks
    cheat_sheets = []
    for fw in stack.get("frameworks", []):
        if fw == "FastAPI":
            cheat_sheets.append(
                "### SOTA FastAPI Reference Card\n"
                "- **Routing**: Use `APIRouter(prefix=..., tags=[...])` with strict Pydantic v2 schemas.\n"
                "- **Dependency Injection**: Use `Annotated[T, Depends(get_db)]` for clean async session lifetimes.\n"
                "- **Tenant Scoping & Dual-Mode Auth**: Use `HttpOnly` cookie (SameSite=Lax) for HTML SSR fallback + strict `Authorization: Bearer` for JSON API."
            )
        elif fw == "Next.js":
            cheat_sheets.append(
                "### SOTA Next.js App Router Reference Card\n"
                "- **Server Actions**: Define with `'use server'` and strict Zod validation.\n"
                "- **State & Cache**: Avoid client hydration mismatches; isolate client components with `'use client'`."
            )
        elif fw == "Docker":
            cheat_sheets.append(
                "### SOTA Docker Production Deployment Card\n"
                "- **Multi-stage builds**: Minimal distroless/alpine final image.\n"
                "- **Healthchecks**: Built-in `HEALTHCHECK` checking `/health` or internal ping."
            )

    for db in stack.get("databases", []):
        if "SQLite" in db:
            cheat_sheets.append(
                "### SOTA SQLite WAL Reference Card\n"
                "- **Concurrency**: `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`\n"
                "- **Read-Your-Own-Writes**: Immediate transaction commit before assistant response."
            )
        elif "asyncpg" in db or "PostgreSQL" in db:
            cheat_sheets.append(
                "### SOTA PostgreSQL asyncpg Reference Card\n"
                "- **Connection Pooling**: Use `asyncpg.create_pool(min_size=2, max_size=10)`.\n"
                "- **Transactions**: `async with pool.acquire() as conn: async with conn.transaction(): ...`"
            )

    if cheat_sheets:
        resources["cheat_sheets"] = "\n\n".join(cheat_sheets)

    return resources

def run_init(target_path: Path, tier: str = "standard", goal: Optional[str] = None) -> Dict[str, Any]:
    scanner = ProjectScanner(target_path)
    stack = scanner.detect_stack()
    structure = scanner.inspect_structure()
    external_reqs = scanner.infer_required_external_knowledge(stack)

    # Fetch deep knowledge if tier is deep or xhigh
    deep_knowledge = {}
    if tier in ["deep", "xhigh"]:
        deep_knowledge = fetch_and_synthesize_deep_knowledge(scanner.target_dir, stack, tier=tier)

    # 1. Generate Obsidian Project Dossier
    OBSIDIAN_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    obsidian_file = OBSIDIAN_PROJECTS_DIR / f"{scanner.name}.md"

    commit_sha = ""
    commit_msg = ""
    branch_name = ""
    try:
        r_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=scanner.target_dir, capture_output=True, text=True, timeout=3)
        if r_sha.returncode == 0:
            commit_sha = r_sha.stdout.strip()
        r_msg = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=scanner.target_dir, capture_output=True, text=True, timeout=3)
        if r_msg.returncode == 0:
            commit_msg = r_msg.stdout.strip()
        r_br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=scanner.target_dir, capture_output=True, text=True, timeout=3)
        if r_br.returncode == 0:
            branch_name = r_br.stdout.strip()
    except Exception:
        pass

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    doc_lines = [
        f"# Project Dossier: {scanner.name}",
        "",
        f"- **Ostatni Commit:** `{commit_sha}` {commit_msg}" if commit_sha else "- **Ostatni Commit:** `initial`",
        f"- **Ostatnia synchronizacja:** `{now_str}`",
        f"- **Git Branch:** `{branch_name or 'main'}`",
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

    if deep_knowledge.get("local_knowhow"):
        doc_lines.extend([
            "",
            "## Linked Obsidian Knowhow Canon",
            deep_knowledge["local_knowhow"]
        ])

    if deep_knowledge.get("cheat_sheets"):
        doc_lines.extend([
            "",
            "## Up-to-Date Architecture & SOTA Contracts",
            deep_knowledge["cheat_sheets"]
        ])

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

    # 3. Operator Scratchpad .planning/THOUGHTS.md if missing
    thoughts_file = planning_dir / "THOUGHTS.md"
    if not thoughts_file.exists():
        thoughts_template = Path.home() / "Documents/Wojciech/templates/sota-starter/THOUGHTS_TEMPLATE.md"
        if thoughts_template.exists():
            t_content = thoughts_template.read_text(encoding="utf-8").replace("{{DATE}}", datetime.now().strftime("%Y-%m-%d"))
        else:
            t_content = f"# Operator Thoughts & Advisory Scratchpad (Wojciech)\n\n> To jest prywatny scratchpad operatora projektu.\n\n---\n\n## [{datetime.now().strftime('%Y-%m-%d')}] Przemyslenia & Wątki do rozważenia\n- [ ] Luźny pomysł lub uwaga architektoniczna...\n"
        thoughts_file.write_text(t_content, encoding="utf-8")

    # 4. Architecture Diagram .planning/ARCHITECTURE.mmd if missing
    arch_file = planning_dir / "ARCHITECTURE.mmd"
    if not arch_file.exists():
        arch_template = Path.home() / "Documents/Wojciech/templates/sota-starter/ARCHITECTURE_TEMPLATE.mmd"
        if arch_template.exists():
            a_content = arch_template.read_text(encoding="utf-8")
        else:
            a_content = "graph TD\n    App[\"Application\"]\n"
        arch_file.write_text(a_content, encoding="utf-8")

    # 5. Visual Cockpit .planning/state.html
    builder_script = Path.home() / "Documents/Wojciech/templates/sota-starter/build_state_template.js"
    if builder_script.exists():
        try:
            subprocess.run(["node", str(builder_script), str(target_path)], capture_output=True, timeout=5)
        except Exception:
            pass

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
    known_cmds = {"init", "mode", "config", "configure", "off", "on", "status", "doctor", "stream", "jev", "-h", "--help"}
    if len(sys.argv) > 1 and sys.argv[1] not in known_cmds:
        sys.argv.insert(1, "init")

    parser = argparse.ArgumentParser(description="Hermes JIT Context OS — CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # jit init
    init_parser = subparsers.add_parser("init", help="Initialize and profile project context")
    init_parser.add_argument("path", nargs="?", default=".", help="Target project path")
    init_parser.add_argument("--tier", choices=["simple", "standard", "deep", "xhigh"], default="standard", help="Initialization depth")
    init_parser.add_argument("--goal", type=str, default=None, help="Explicit project goal")

    # jit mode
    mode_parser = subparsers.add_parser("mode", help="Get or set JIT operating mode (active, shadow, passive, off)")
    mode_parser.add_argument("target_mode", nargs="?", choices=["active", "shadow", "passive", "off"], default=None, help="Operating mode to set")

    # jit config / configure
    config_parser = subparsers.add_parser("config", aliases=["configure"], help="View or modify JIT configuration settings")
    config_parser.add_argument("action", nargs="?", default="show", help="Action (show, get, set) or config key")
    config_parser.add_argument("key_or_val", nargs="?", default=None, help="Key name or value")
    config_parser.add_argument("val", nargs="?", default=None, help="Value when using 'set <key> <val>'")

    subparsers.add_parser("off", help="Disable JIT context injection")
    subparsers.add_parser("on", help="Enable JIT context injection")
    subparsers.add_parser("status", help="Show JIT context status")
    subparsers.add_parser("doctor", help="Run system health and invariant diagnostics")
    stream_parser = subparsers.add_parser("stream", help="Launch live animated ANSI telemetry stream")
    stream_parser.add_argument("--fps", type=float, default=8.0, help="Frames per second (default: 8)")
    stream_parser.add_argument("--seconds", type=float, default=None, help="Run for N seconds and exit")

    # jit jev
    jev_parser = subparsers.add_parser("jev", help="Run JEV probabilistic decision engine diagnostics and live probe")
    jev_parser.add_argument("action", nargs="?", default="status", choices=["status", "probe", "test"], help="Action (status, probe)")
    jev_parser.add_argument("--query", type=str, default="drzewo decyzyjne i silnik reguł probabilistycznych", help="Test query for JEV probe")

    # Allow running directly as 'jit <path>' without subcommand
    parser.add_argument("direct_path", nargs="?", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--tier", choices=["simple", "standard", "deep", "xhigh"], default="standard", help=argparse.SUPPRESS)
    parser.add_argument("--goal", type=str, default=None, help=argparse.SUPPRESS)
    
    args, unknown = parser.parse_known_args()

    mode_file = Path.home() / ".hermes" / "state" / "ona-context" / "mode.json"
    live_file = Path("/tmp/hermes-jit-live.json")

    cmd = args.command or args.direct_path

    # Subcommand: jit mode
    if cmd == "mode":
        from config import load_config, set_config_val, MODE_FILE
        target = getattr(args, "target_mode", None)
        if not target and unknown:
            for u in unknown:
                if u in ("active", "shadow", "passive", "off"):
                    target = u
                    break
        if target:
            old_mode, new_mode = set_config_val("mode", target)
            icons = {"active": "⚡", "shadow": "🌓", "passive": "👁️", "off": "🛑"}
            icon = icons.get(target, "⚡")
            print("=" * 60)
            print(f"{icon} JIT CONTEXT OS — TRYB PRZEŁĄCZONY: {target.upper()}")
            print("=" * 60)
            if target == "active":
                print("• Status: ACTIVE — pełne dynamiczne wstrzykiwanie kapsuły JIT (<1,500 tok)")
            elif target == "shadow":
                print("• Status: SHADOW — kapsuła jest kompilowana i logowana do telemetrii, lecz nie wstrzykiwana")
            elif target == "passive":
                print("• Status: PASSIVE — lekki nasłuch bez aktywnej kompilacji promptu")
            elif target == "off":
                print("• Status: OFF — JIT Context OS całkowicie wyłączony")
            print(f"• Zapisano w: {MODE_FILE}")
            print("=" * 60)
            return

        cfg = load_config()
        cur_mode = cfg.get("mode", "active")
        print("=" * 60)
        print("⚡ HERMES JIT CONTEXT OS — AKTUALNY TRYB")
        print("=" * 60)
        print(f"• Tryb bieżący: {cur_mode.upper()}")
        print(f"• Dostępne tryby: active, shadow, passive, off")
        print("\nOpis trybów:")
        print("  active   - Pełne automatyczne wstrzykiwanie lean kapsuły (<1.5k tok)")
        print("  shadow   - Kompilacja i pomiary w tle (telemetria), bez ingerencji w prompt")
        print("  passive  - Tryb pasywny (tylko rejestracja zdarzeń)")
        print("  off      - Całkowite wyłączenie silnika")
        print("\nSzybkie przełączanie:")
        print("  jit mode <active|shadow|passive|off>")
        print("  jit on  /  jit off")
        print("=" * 60)
        return

    # Subcommand: jit config / configure
    if cmd in ("config", "configure"):
        from config import load_config, set_config_val, get_config_val, CONFIG_DESCRIPTIONS, MODE_FILE
        cfg = load_config()

        action = getattr(args, "action", "show") or "show"
        p1 = getattr(args, "key_or_val", None)
        p2 = getattr(args, "val", None)

        # Syntax 1: jit config set <key> <val>
        if action == "set":
            if not p1 or p2 is None:
                print("❌ Użycie: jit config set <klucz> <wartość>")
                return
            old_val, new_val = set_config_val(p1, p2)
            print("=" * 60)
            print(f"⚙️  JIT CONTEXT OS — ZAKTUALIZOWANO KONFIGURACJĘ")
            print("=" * 60)
            print(f"• {p1} = {repr(new_val)} (poprzednio: {repr(old_val)})")
            print(f"• Zapisano w: {MODE_FILE}")
            print("=" * 60)
            return

        # Syntax 2: jit config get <key>
        if action == "get":
            if not p1:
                print("❌ Użycie: jit config get <klucz>")
                return
            val = get_config_val(p1)
            print(val)
            return

        # Syntax 3: jit config <key> <val> (shortcut for set)
        if action in cfg and p1 is not None:
            old_val, new_val = set_config_val(action, p1)
            print("=" * 60)
            print(f"⚙️  JIT CONTEXT OS — ZAKTUALIZOWANO KONFIGURACJĘ")
            print("=" * 60)
            print(f"• {action} = {repr(new_val)} (poprzednio: {repr(old_val)})")
            print(f"• Zapisano w: {MODE_FILE}")
            print("=" * 60)
            return

        # Syntax 4: jit config <key> (shortcut for get)
        if action in cfg and p1 is None:
            val = get_config_val(action)
            print(val)
            return

        # Syntax 5: jit config / jit config show / jit config list
        print("=" * 70)
        print("⚙️  HERMES JIT CONTEXT OS — KONFIGURACJA RUNTIME")
        print("=" * 70)
        print(f"Plik konfiguracyjny: {MODE_FILE}\n")
        print(f"{'PARAMETR':<26} {'WARTOŚĆ':<20} {'OPIS'}")
        print("─" * 70)
        for k, v in cfg.items():
            if k == "updated_at":
                continue
            desc = CONFIG_DESCRIPTIONS.get(k, "")
            v_str = str(v)
            if len(v_str) > 18:
                v_str = v_str[:15] + "..."
            print(f"{k:<26} {v_str:<20} {desc}")
        print("─" * 70)
        print("\nPolecenia:")
        print("  jit config set <klucz> <wartość>  Ustaw parametr (np. jit config set worker qwen)")
        print("  jit config get <klucz>            Pobierz wartość parametru")
        print("  jit mode <tryb>                   Szybka zmiana trybu (active, shadow, passive, off)")
        print("=" * 70)
        return

    if cmd == "off":
        from config import set_config_val
        set_config_val("mode", "off")
        print("=" * 60)
        print("🛑 JIT CONTEXT OS — WYŁĄCZONY (OFF)")
        print("=" * 60)
        print("• Status: off (brak wstrzykiwania kapsuły kontekstu <ONA_CONTEXT>)")
        print("• Aby włączyć ponownie: jit on  lub  jit mode active")
        print("=" * 60)
        return

    if cmd == "on":
        from config import set_config_val
        set_config_val("mode", "active")
        print("=" * 60)
        print("⚡ JIT CONTEXT OS — AKTYWNY (ACTIVE)")
        print("=" * 60)
        print("• Status: active (automatyczne wstrzykiwanie kapsuły kontekstu JIT)")
        print("• Aby wyłączyć: jit off  lub  jit mode off")
        print("=" * 60)
        return

    if cmd == "status":
        from config import load_config, MODE_FILE
        cfg = load_config()
        current_mode = cfg.get("mode", "active")
        worker = cfg.get("worker", "routed")
        tier = cfg.get("tier", "standard")
        thresh = cfg.get("compaction_threshold", 0.4)
        c_window = cfg.get("context_window", 1000000)
        print("=" * 60)
        print(f"⚡ JIT CONTEXT OS — STATUS: {current_mode.upper()}")
        print("=" * 60)
        print(f"• Tryb runtime:         {current_mode}")
        print(f"• Domyślny Ego Worker:  {worker}")
        print(f"• Profiling Tier:       {tier}")
        print(f"• Próg kompaktowania:   {thresh} (~{int(c_window * thresh):,} tokens)")
        print(f"• Plik konfiguracyjny:  {MODE_FILE}")
        print("=" * 60)
        return

    if cmd == "doctor":
        try:
            from health.doctor import run_doctor
            success = run_doctor()
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"Błąd uruchamiania doctor: {e}", file=sys.stderr)
            sys.exit(1)

    if cmd == "stream":
        try:
            from telemetry.stream import run_stream_loop
            run_stream_loop(fps=getattr(args, "fps", 8.0), max_seconds=getattr(args, "seconds", None))
            return
        except Exception as e:
            print(f"Błąd uruchamiania stream: {e}", file=sys.stderr)
            sys.exit(1)

    if cmd == "jev":
        try:
            import time
            from cognitive.jev_engine import get_jev_scorer, DECISIONS_URL, DEFAULT_MODEL
            scorer = get_jev_scorer()
            query = getattr(args, "query", "drzewo decyzyjne i silnik reguł probabilistycznych")
            print("=" * 60)
            print(" ⚡ HERMES JIT CONTEXT OS — JEV DECISION ENGINE")
            print("=" * 60)
            print(f"• Model upstream:       {scorer.model}")
            print(f"• Endpoint API:         {DECISIONS_URL}")
            key = scorer.api_key
            masked_key = (key[:8] + "..." + key[-4:]) if (key and len(key) > 12) else ("Brak klucza" if not key else "sk-...")
            key_status = "[PASS]" if key else "[WARN / OFFLINE FALLBACK]"
            cb_status = "ALLOWED" if scorer._breaker.allow_request() else "TRIPPED"
            print(f"• API Key (JEV):        {masked_key} {key_status}")
            print(f"• Circuit Breaker:      {cb_status}")
            print(f"• Cache TTL:            {scorer.ttl_s}s")
            print("─" * 60)
            print("🔍 LIVE PROBE & HYBRID RERANKING TEST:")
            candidates = [
                {"key": "fact_0", "value": "Silnik decyzji probabilistycznych JEV typu typesafe w Hermesie"},
                {"key": "fact_1", "value": "Wojciech buduje architekturę JIT Context OS i mechanizmy epistemiczne"},
                {"key": "fact_2", "value": "Kot ma cztery łapy i lubi spać na kanapie"}
            ]
            t0 = time.time()
            raw_scores = scorer.score_remote(query, candidates)
            latency_ms = (time.time() - t0) * 1000.0
            if raw_scores:
                print(f"• Upstream Probe:       PASS ({latency_ms:.1f}ms)")
                for k, score in raw_scores.items():
                    print(f"   ├─ {k}: score={score:.2f}")
            else:
                print(f"• Upstream Probe:       FALLBACK (deterministic tokens, latency {latency_ms:.1f}ms)")

            reranked = scorer.rerank_hybrid(query, candidates)
            print("• Wynik Hybrid Reranking (Invariant I6):")
            for i, r in enumerate(reranked):
                k = r["key"]
                val = r["value"][:55]
                print(f"   [{i+1}] {k}: {val}...")
            print("=" * 60)
            return
        except Exception as e:
            print(f"Błąd uruchamiania JEV: {e}", file=sys.stderr)
            sys.exit(1)

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
