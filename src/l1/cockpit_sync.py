"""Cockpit freshness for one repo: rebuild .planning/state.html and flag a stale architecture diagram.

Called from the git post-commit hook (via l1/post_commit.py) and from the capsule builder in hooks.py.
Both checks are cheap (one node call, two git calls) and never raise: a broken cockpit must not block a commit.
"""

import subprocess
from pathlib import Path
from typing import Optional, Tuple

BUILDER_SCRIPT = Path.home() / "Documents/Wojciech/templates/sota-starter/build_state_template.js"
ARCHITECTURE_FILE = ".planning/ARCHITECTURE.mmd"
COCKPIT_FILE = ".planning/state.html"
# Commits touching code since the diagram last changed, before we call the diagram stale.
ARCHITECTURE_STALE_COMMITS = 15
# Paths that do not change the architecture (docs, planning, changelogs).
NON_CODE_PATHSPECS = [":(exclude).planning", ":(exclude)docs", ":(exclude)*.md"]


def _git(repo: Path, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def is_tracked(repo: Path, rel_path: str) -> bool:
    return _git(repo, "ls-files", "--error-unmatch", rel_path) is not None


def regenerate_cockpit(repo: Path, builder: Path = BUILDER_SCRIPT) -> Tuple[bool, str]:
    """Rebuild state.html from STATE.md, git and the diagram. Skips repos that commit state.html,
    because rebuilding after every commit would leave their tree permanently dirty."""
    repo = Path(repo)
    if not (repo / ".planning").is_dir():
        return False, "no .planning/ directory"
    if not builder.exists():
        return False, f"builder missing: {builder}"
    if is_tracked(repo, COCKPIT_FILE):
        return False, f"{COCKPIT_FILE} is tracked in git; run the builder by hand"
    try:
        r = subprocess.run(["node", str(builder), str(repo)], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return False, f"builder failed: {e}"
    if r.returncode != 0:
        return False, f"builder exit {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}"
    return True, f"rebuilt {COCKPIT_FILE}"


def architecture_drift(repo: Path, threshold: int = ARCHITECTURE_STALE_COMMITS) -> Optional[str]:
    """Return a Polish warning when code moved on and ARCHITECTURE.mmd did not, else None."""
    repo = Path(repo)
    if not (repo / ARCHITECTURE_FILE).exists():
        return None
    diagram_sha = _git(repo, "log", "-1", "--format=%h", "--", ARCHITECTURE_FILE)
    if not diagram_sha:
        return None  # diagram never committed: nothing to compare against yet
    count = _git(repo, "rev-list", "--count", f"{diagram_sha}..HEAD", "--", ".", *NON_CODE_PATHSPECS)
    if count is None or not count.isdigit() or int(count) < threshold:
        return None
    return (f"Diagram {ARCHITECTURE_FILE} jest nieaktualny: {count} commitów w kodzie od ostatniej zmiany "
            f"({diagram_sha}). Przerysuj go według faktycznych modułów.")
