"""`jit install` / `jit uninstall`: wire JIT Context into every agent host found on this machine."""

from __future__ import annotations

import argparse

from installer import agent_zero, claude_code, hermes, opencode
from installer.common import FAIL, Result

HOSTS = {
    claude_code.HOST: claude_code,
    hermes.HOST: hermes,
    opencode.HOST: opencode,
    agent_zero.HOST: agent_zero,
}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--only", default="", help="Comma-separated hosts: " + ",".join(HOSTS))
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, change nothing")


def selected_hosts(only: str) -> list[str]:
    names = [n.strip() for n in only.split(",") if n.strip()] or list(HOSTS)
    unknown = [n for n in names if n not in HOSTS]
    if unknown:
        raise SystemExit(f"unknown host(s): {', '.join(unknown)}; choose from {', '.join(HOSTS)}")
    return names


def run(action: str, only: str = "", dry_run: bool = False) -> list[Result]:
    results = []
    for name in selected_hosts(only):
        module = HOSTS[name]
        try:
            results.append(getattr(module, action)(dry_run=dry_run))
        except Exception as exc:  # one broken host must not stop the others
            results.append(Result(name, FAIL, f"{type(exc).__name__}: {exc}"))
    return results


def print_table(results: list[Result]) -> None:
    width = max(len(r.host) for r in results)
    for r in results:
        print(f"  {r.host:<{width}}  {r.status:<7}  {r.detail}")


def main(action: str, args: argparse.Namespace) -> int:
    print(f"JIT Context {action}:")
    results = run(action, args.only, args.dry_run)
    print_table(results)
    return 1 if any(r.status == FAIL for r in results) else 0
