"""Git post-commit entry point: keep the Obsidian dossier and the project cockpit in step with the commit.

Usage (from .git/hooks/post-commit): python3 ~/.jit-context/src/l1/post_commit.py "$(git rev-parse --show-toplevel)"
Always exits 0; a post-commit hook must never fail the commit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from l1.cockpit_sync import architecture_drift, regenerate_cockpit  # noqa: E402
from l1.obsidian_sync import sync_obsidian_on_commit  # noqa: E402


def run(repo: Path) -> list:
    lines = []
    ok, msg = sync_obsidian_on_commit(repo.name, str(repo))
    if ok:
        lines.append(f"[obsidian-sync] {msg}")
    ok, msg = regenerate_cockpit(repo)
    if ok:
        lines.append(f"[cockpit] {msg}")
    drift = architecture_drift(repo)
    if drift:
        lines.append(f"[cockpit] {drift}")
    return lines


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    try:
        for line in run(Path(sys.argv[1]).resolve()):
            print(line)
    except Exception as e:
        print(f"[post-commit] skipped: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
