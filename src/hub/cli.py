"""CLI for `jit hub scan [root]` and `jit hub list`, plus the registration hook used by `jit init`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import config
from hub import registry
from hub.scan import MAX_SCAN_DEPTH, ScanReport, scan

EXIT_USAGE = 2
MISSING = "brak"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="hub_action")
    scan_parser = actions.add_parser("scan", help="Register every repo with .planning/STATE.md or jit.json")
    scan_parser.add_argument("root", nargs="?", default=None, help=f"Root to scan (default: {config.WORKSPACE_DIR})")
    scan_parser.add_argument("--max-depth", type=int, default=MAX_SCAN_DEPTH, help="Directory depth limit")
    list_parser = actions.add_parser("list", help="Print the project registry")
    list_parser.add_argument("--json", action="store_true", help="Print raw JSON entries")


def _print_scan(report: ScanReport) -> None:
    print(f"Hub: skan {report.root}")
    print(f"  Nowe w rejestrze: {len(report.registered)}")
    for entry in report.registered:
        print(f"    + {entry['slug']}  {entry['path']}")
    print(f"  Już znane: {len(report.known)}")
    print(f"  Pominięte worktree: {len(report.skipped_worktrees)}")
    print(f"  Repozytoria bez .planning/STATE.md i .planning/jit.json: {report.unmarked_repos}")
    print(f"  Błędy git: {len(report.git_errors)}")
    for path in report.git_errors:
        print(f"    ! {path}")
    print(f"  Rejestr: {registry.registry_path()}")


def _run_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser() if args.root else config.WORKSPACE_DIR
    if not root.is_dir():
        print(f"jit hub scan: katalog nie istnieje: {root}")
        return EXIT_USAGE
    _print_scan(scan(root, max_depth=args.max_depth))
    return 0


def _run_list(args: argparse.Namespace) -> int:
    entries = registry.load_projects()
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print(f"Rejestr pusty: {registry.registry_path()}")
        return 0
    width = max(len(entry["slug"]) for entry in entries)
    for entry in sorted(entries, key=lambda e: e["slug"]):
        last_init = entry.get("last_init_at") or MISSING
        print(f"{entry['slug']:<{width}}  {entry['path']}  init: {last_init}")
    print(f"Projekty: {len(entries)}  Rejestr: {registry.registry_path()}")
    return 0


def main(args: argparse.Namespace) -> int:
    action = getattr(args, "hub_action", None)
    if action == "scan":
        return _run_scan(args)
    if action == "list":
        return _run_list(args)
    print("Użycie: jit hub scan [root] | jit hub list [--json]")
    return EXIT_USAGE


def register_after_init(target_dir: Path) -> str:
    """Register a freshly initialised project; returns one report line (errors are reported, not hidden)."""
    try:
        entry, created = registry.register_project(target_dir, from_init=True)
    except OSError as exc:
        return f"• Hub: rejestracja nieudana: {exc}"
    state = "nowy wpis" if created else "wpis zaktualizowany"
    return f"• Hub: {entry['slug']} ({state}) -> {registry.registry_path()}"
