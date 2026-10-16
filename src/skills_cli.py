"""`jit skills` CLI: show / write the per-project skill selection, sync skills into a worktree."""

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

from context.skill_output import write_selection
from context.skill_selector import Selection, select_skills

WORKTREE_SKILLS_SUBDIR = Path(".claude") / "skills"
SYNC_ACTION = "sync"


def select_for_path(project: Path, stack: Optional[Dict] = None, **roots) -> Selection:
    """Select skills for a project, detecting the stack and Obsidian dossier when not given."""
    project = project.resolve()
    if stack is None:
        from init import ProjectScanner
        stack = ProjectScanner(project).detect_stack()
    if "dossier_file" not in roots:
        from init import resolve_dossier
        roots["dossier_file"] = resolve_dossier(project.name)[0]
    return select_skills(project, stack, **roots)


def write_project_skills(project: Path, stack: Dict, dossier_file: Path) -> Dict[str, str]:
    """Called by `jit init`: select and persist skills. Never breaks init on failure."""
    try:
        selection = select_for_path(project, stack=stack, dossier_file=dossier_file)
        return write_selection(project.resolve(), selection)
    except Exception as exc:  # init must succeed even without a skill base
        return {"error": str(exc)}


def format_selection(selection: Selection) -> str:
    lines: List[str] = []
    for title, picks in (("MUST", selection.must), ("OPTIONAL", selection.optional), ("KNOWHOW", selection.knowhow)):
        lines.append(f"{title} ({len(picks)})")
        lines.extend(f"  {pick.score:7.2f}  {pick.name}  - {pick.reason}" for pick in picks)
    return "\n".join(lines)


def sync_to_worktree(selection: Selection, worktree: Path) -> List[str]:
    """Symlink must-have skill dirs into <worktree>/.claude/skills/<name>. Returns linked names."""
    target_root = worktree / WORKTREE_SKILLS_SUBDIR
    target_root.mkdir(parents=True, exist_ok=True)
    linked = []
    for pick in selection.must:
        link = target_root / pick.name
        if link.is_symlink() or link.exists():
            continue
        os.symlink(Path(pick.path).parent, link)
        linked.append(pick.name)
    return linked


def add_arguments(parser) -> None:
    parser.add_argument("path", nargs="?", default=".", help="Project path, or 'sync' followed by a worktree path")
    parser.add_argument("worktree", nargs="?", default=None, help="Worktree path (with 'sync')")
    parser.add_argument("--write", action="store_true", help="Write .planning/SKILLS.md and jit.json")


def main(args) -> int:
    if args.path == SYNC_ACTION:
        if not args.worktree:
            print("usage: jit skills sync <worktree>")
            return 2
        worktree = Path(args.worktree).resolve()
        linked = sync_to_worktree(select_for_path(worktree), worktree)
        print(f"linked {len(linked)} skill(s) into {worktree / WORKTREE_SKILLS_SUBDIR}: {', '.join(linked)}")
        return 0
    project = Path(args.path).resolve()
    selection = select_for_path(project)
    print(format_selection(selection))
    if args.write:
        written = write_selection(project, selection)
        if "skipped" in written:
            print(written["skipped"])
            return 1
        print(f"wrote {written['skills_md']}, {written['profile']} and {written['allowlist']}")
    return 0
