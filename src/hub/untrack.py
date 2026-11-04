"""`jit cockpit untrack [path]`: stop tracking a generated cockpit in git, only after an explicit yes. Never commits."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

COCKPIT_RELATIVE = Path(".planning") / "state.html"
GITIGNORE_NAME = ".gitignore"
GIT_TIMEOUT_SECONDS = 10
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NEEDS_CONFIRMATION = 2
EXIT_USAGE = 2
YES_ANSWERS = {"t", "tak", "y", "yes"}
COMMIT_MESSAGE = "chore(cockpit): stop tracking the generated cockpit"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="cockpit_action")
    untrack_parser = actions.add_parser("untrack", help="Add .planning/state.html to .gitignore and git rm --cached it")
    untrack_parser.add_argument("path", nargs="?", default=".",
                                help="Project directory or the cockpit file itself (default: .)")
    untrack_parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")


def _git(repo: Path, *args: str) -> Tuple[int, str]:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return EXIT_FAILED, str(exc)
    return res.returncode, (res.stdout if res.returncode == 0 else res.stderr).strip()


def resolve_cockpit(path: Path) -> Path:
    """A directory means its .planning/state.html; any other path is taken as the cockpit file."""
    path = Path(path).expanduser().absolute()
    return path / COCKPIT_RELATIVE if path.is_dir() else path


def _gitignore_has(gitignore: Path, entry: str) -> bool:
    if not gitignore.is_file():
        return False
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines()}
    return entry in lines or "/" + entry in lines


def _append_gitignore(gitignore: Path, entry: str) -> bool:
    """Append `entry` unless present; returns True when the file changed."""
    if _gitignore_has(gitignore, entry):
        return False
    current = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.is_file() else ""
    prefix = "" if not current or current.endswith("\n") else "\n"
    with gitignore.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}{entry}\n")
    return True


def _confirm(entry: str, interactive: bool, ask: Callable[[str], str]) -> Optional[int]:
    """None = go ahead; otherwise the exit code to stop with (nothing changed)."""
    if not interactive:
        print("Brak potwierdzenia: tryb nieinteraktywny. Nic nie zmieniono. Uruchom ponownie z --yes.")
        return EXIT_NEEDS_CONFIRMATION
    try:
        answer = ask(f"Usunąć {entry} z indeksu git (plik zostaje na dysku)? [t/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in YES_ANSWERS:
        return None
    print("Przerwano. Nic nie zmieniono.")
    return EXIT_FAILED


def _print_commit_hint(top: Path, entry: str, gitignore_changed: bool) -> None:
    print("Nie wykonano commita. Do zatwierdzenia (sprawdź najpierw git status):")
    if gitignore_changed:
        print(f"  git -C {top} add {GITIGNORE_NAME}")
    print(f'  git -C {top} commit -m "{COMMIT_MESSAGE}"')
    print(f"  (zmiany: usunięcie {entry} z indeksu" + (f", nowa linia w {GITIGNORE_NAME})" if gitignore_changed else ")"))


def untrack(path: Path, assume_yes: bool, interactive: bool, ask: Callable[[str], str] = input) -> int:
    """Untrack the cockpit under `path`; returns the process exit code."""
    cockpit = resolve_cockpit(path)
    base = cockpit.parent
    while not base.is_dir() and base != base.parent:
        base = base.parent
    code, out = _git(base, "rev-parse", "--show-toplevel")
    if code != 0:
        print(f"jit cockpit untrack: to nie jest repozytorium git: {path} ({out or 'brak szczegółów'})")
        return EXIT_FAILED
    top = Path(out).resolve()
    try:
        entry = cockpit.resolve().relative_to(top).as_posix()
    except ValueError:
        print(f"jit cockpit untrack: {cockpit} leży poza repozytorium {top}")
        return EXIT_FAILED
    code, listed = _git(top, "ls-files", "--", entry)
    if code != 0:
        print(f"jit cockpit untrack: git ls-files nieudane: {listed}")
        return EXIT_FAILED
    if not listed:
        ignored = _gitignore_has(top / GITIGNORE_NAME, entry)
        print(f"{entry} nie jest śledzony w {top}. Nic do zrobienia"
              + ("." if ignored else f" (brak wpisu w {GITIGNORE_NAME})."))
        return EXIT_OK
    print(f"{entry} jest śledzony w {top}.")
    print(f"Plan: dopisać {entry} do {GITIGNORE_NAME} i wykonać git rm --cached (plik zostaje na dysku).")
    if not assume_yes:
        stop = _confirm(entry, interactive, ask)
        if stop is not None:
            return stop
    code, detail = _git(top, "rm", "--cached", "--quiet", "--", entry)
    if code != 0:
        print(f"jit cockpit untrack: git rm --cached nieudane: {detail}")
        return EXIT_FAILED
    try:
        changed = _append_gitignore(top / GITIGNORE_NAME, entry)
    except OSError as exc:
        print(f"jit cockpit untrack: plik usunięty z indeksu, ale zapis {GITIGNORE_NAME} nieudany: {exc}")
        return EXIT_FAILED
    print(f"Usunięto z indeksu: {entry}. {GITIGNORE_NAME}: " + ("dopisano linię." if changed else "wpis już był."))
    _print_commit_hint(top, entry, changed)
    return EXIT_OK


def main(args: argparse.Namespace) -> int:
    if getattr(args, "cockpit_action", None) == "untrack":
        return untrack(Path(args.path), args.yes, sys.stdin.isatty())
    print("Użycie: jit cockpit untrack [ścieżka] [--yes]")
    return EXIT_USAGE
