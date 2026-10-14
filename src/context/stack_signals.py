"""Stack signals shared by `jit init` and the capsule verify-command heuristic.

One place for: package-manager resolution from lockfiles, Node dependency to
framework mapping, "is this language real or just helper scripts" detection,
the verify command and the external-knowledge table.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Highest priority first. A repo with several lockfiles uses the first match.
LOCKFILE_PRIORITY = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("package-lock.json", "npm"),
)
DEFAULT_PACKAGE_MANAGER = "npm"

PYTHON_MANIFESTS = ("pyproject.toml", "setup.py", "Pipfile")
PYTHON_VERIFY_MARKERS = ("pyproject.toml", "setup.py", "pytest.ini", "conftest.py")

# Directories whose source files are tooling, not the product.
HELPER_DIRS = {"scripts", "tools", "bin", "docs"}
SKIP_DIRS = {
    "node_modules", ".git", ".next", "venv", ".venv", "__pycache__",
    "dist", "build", ".turbo",
}
SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".rs": "Rust", ".go": "Go",
}
MIN_LANGUAGE_SHARE = 0.3
MAX_SCANNED_FILES = 2000
MAX_CONTENT_FILES = 20

NODE_FRAMEWORKS = {
    "next": "Next.js", "react": "React", "astro": "Astro", "vue": "Vue",
    "svelte": "Svelte", "@sveltejs/kit": "SvelteKit", "lit": "Lit",
    "express": "Express", "fastify": "Fastify", "hono": "Hono",
    "tailwindcss": "Tailwind", "vite": "Vite", "nuxt": "Nuxt",
    "@angular/core": "Angular",
}
NODE_DATABASES = {"prisma": "Prisma", "@prisma/client": "Prisma", "drizzle-orm": "Drizzle"}
NODE_TEST_RUNNERS = {
    "vitest": "Vitest", "jest": "Jest", "mocha": "Mocha",
    "@playwright/test": "Playwright", "playwright": "Playwright",
}
NODE_LIBRARIES = {"@google/genai": "@google/genai"}

# Detected signal (framework, database, language, test runner, library) -> docs to pull.
EXTERNAL_KNOWLEDGE: Dict[str, Dict[str, str]] = {
    "FastAPI": {"type": "context7", "target": "fastapi", "description": "Latest FastAPI routing & async dependency injection"},
    "Next.js": {"type": "context7", "target": "next", "description": "Next.js App Router & Server Actions API"},
    "Docker": {"type": "knowhow", "target": "devops/deployment-pitfalls", "description": "Borg tools Docker deployment canon"},
    "SQLModel": {"type": "context7", "target": "sqlmodel", "description": "SQLModel AsyncEngine & Pydantic v2 validation"},
    "SQLAlchemy": {"type": "context7", "target": "sqlmodel", "description": "SQLModel AsyncEngine & Pydantic v2 validation"},
    "Prisma": {"type": "context7", "target": "prisma", "description": "Prisma client schema migration rules"},
    "Vite": {"type": "context7", "target": "vite", "description": "Vite config, plugins and build pipeline"},
    "Vitest": {"type": "context7", "target": "vitest", "description": "Vitest runner, mocking and config"},
    "TypeScript": {"type": "context7", "target": "typescript", "description": "TypeScript compiler options and type system"},
    "React": {"type": "context7", "target": "react", "description": "React hooks and rendering model"},
    "Svelte": {"type": "context7", "target": "svelte", "description": "Svelte components and reactivity"},
    "Vue": {"type": "context7", "target": "vue", "description": "Vue composition API"},
    "Lit": {"type": "context7", "target": "lit", "description": "Lit web components and reactive properties"},
    "Tailwind": {"type": "context7", "target": "tailwindcss", "description": "Tailwind utility classes and config"},
    "Pydantic": {"type": "context7", "target": "pydantic", "description": "Pydantic v2 models and validation"},
    "pytest": {"type": "context7", "target": "pytest", "description": "pytest fixtures, parametrization and plugins"},
    "Playwright": {"type": "context7", "target": "playwright", "description": "Playwright browser automation and test API"},
    "@google/genai": {"type": "context7", "target": "google-genai", "description": "Google GenAI JS SDK"},
}


def detect_package_manager(project_dir: Path) -> Optional[str]:
    """Package manager implied by the lockfile, or None when there is no lockfile."""
    for lockfile, manager in LOCKFILE_PRIORITY:
        if (project_dir / lockfile).exists():
            return manager
    return None


def read_package_json(pkg_path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def node_test_command(project_dir: Path) -> Optional[str]:
    """`<pm> run test` when package.json declares scripts.test."""
    scripts = read_package_json(project_dir / "package.json").get("scripts")
    if not isinstance(scripts, dict) or not scripts.get("test"):
        return None
    return f"{detect_package_manager(project_dir) or DEFAULT_PACKAGE_MANAGER} run test"


def infer_verify_command(project_dir: Path) -> Optional[str]:
    """Verify command for a project root. Never guesses pytest from tests/ next to package.json."""
    node_cmd = node_test_command(project_dir)
    if node_cmd:
        return node_cmd
    if (project_dir / "Cargo.toml").exists():
        return "cargo test"
    if any((project_dir / name).exists() for name in PYTHON_VERIFY_MARKERS):
        return "pytest"
    if (project_dir / "tests").exists() and not (project_dir / "package.json").exists():
        return "pytest"
    return None


def parse_node_package(pkg_path: Path) -> Dict[str, Any]:
    """Frameworks, databases, test runners, libraries and language from one package.json."""
    data = read_package_json(pkg_path)
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
    return {
        "language": "TypeScript" if "typescript" in deps else "JavaScript",
        "frameworks": [label for dep, label in NODE_FRAMEWORKS.items() if dep in deps],
        "databases": [label for dep, label in NODE_DATABASES.items() if dep in deps],
        "test_runners": [label for dep, label in NODE_TEST_RUNNERS.items() if dep in deps],
        "libraries": [label for dep, label in NODE_LIBRARIES.items() if dep in deps],
        "test_script": scripts.get("test"),
    }


def scan_source_files(target_dir: Path) -> Dict[str, Any]:
    """Count source files per language, split into product code and helper-dir code."""
    product: Dict[str, int] = {}
    helper: Dict[str, int] = {}
    python_files: List[Path] = []
    scanned = 0
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        in_helper = bool(HELPER_DIRS & set(Path(root).relative_to(target_dir).parts))
        for name in files:
            language = SOURCE_EXTENSIONS.get(os.path.splitext(name)[1])
            if not language:
                continue
            scanned += 1
            bucket = helper if in_helper else product
            bucket[language] = bucket.get(language, 0) + 1
            if language == "Python" and not in_helper and len(python_files) < MAX_CONTENT_FILES:
                python_files.append(Path(root) / name)
        if scanned >= MAX_SCANNED_FILES:
            break
    return {"product": product, "helper": helper, "python_files": python_files}


def classify_python(target_dir: Path) -> Dict[str, Any]:
    """Decide whether Python is a primary language or only helper scripts."""
    scan = scan_source_files(target_dir)
    has_manifest = any((target_dir / name).exists() for name in PYTHON_MANIFESTS) or any(
        target_dir.glob("requirements*.txt")
    )
    product = scan["product"]
    total = sum(product.values())
    share = product.get("Python", 0) / total if total else 0.0
    primary = has_manifest or share >= MIN_LANGUAGE_SHARE
    helper_only = not primary and (scan["helper"].get("Python", 0) > 0 or product.get("Python", 0) > 0)
    return {
        "primary": primary,
        "helper_only": helper_only,
        "files": scan["python_files"] if primary else [],
    }


def knowledge_for_stack(stack: Dict[str, Any]) -> List[Dict[str, str]]:
    """External docs to fetch for every detected signal, de-duplicated by (type, target)."""
    signals: List[str] = []
    for key in ("frameworks", "databases", "languages", "test_runners", "libraries"):
        signals.extend(stack.get(key, []))
    unique: List[Dict[str, str]] = []
    seen = set()
    for signal in signals:
        resource = EXTERNAL_KNOWLEDGE.get(signal)
        if not resource:
            continue
        key = (resource["type"], resource["target"])
        if key not in seen:
            seen.add(key)
            unique.append(dict(resource))
    return unique
