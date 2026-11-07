"""CLI for `jit feedby`: the Feedby default for every project.

  jit feedby inventory [--days 30]          live repos (commits in N days) vs the rollout plan
  jit feedby provision <repo-key>|--live    Feedby project + widget key + managed snippet + commit
                       [--dry-run] [--no-commit]
  jit feedby verify [<repo-key>|--live]     key accepted by Feedby, snippet present, live page serves it

The rollout plan <hub_dir>/feedby/plan.json maps repo keys to {path, slug, name, mounts, locale, url}.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from feedby_std import inventory, provision, store, verify

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="feedby_action")
    inv = actions.add_parser("inventory", help="Live repos vs rollout plan")
    inv.add_argument("--days", type=int, default=inventory.LIVE_WINDOW_DAYS)
    for name in ("provision", "verify"):
        sub = actions.add_parser(name, help=f"{name.capitalize()} Feedby for planned repos")
        sub.add_argument("repo", nargs="?", default=None, help="Repo key from plan.json")
        sub.add_argument("--live", action="store_true", help="All planned repos with commits in --days")
        sub.add_argument("--days", type=int, default=inventory.LIVE_WINDOW_DAYS)
        sub.add_argument("--json", action="store_true", help="Print results as JSON")
        if name == "provision":
            sub.add_argument("--dry-run", action="store_true", help="Show what would change, change nothing")
            sub.add_argument("--no-commit", action="store_true", help="Write mount files but do not commit")


def _selected(args: argparse.Namespace, plan: Dict[str, Dict[str, Any]]) -> List[str]:
    if args.repo:
        return [args.repo] if args.repo in plan else []
    if not args.live:
        return []
    live_paths = {row["path"] for row in inventory.live_repos(args.days)}
    return [key for key, item in plan.items() if item["path"] in live_paths and not item.get("skip")]


def _run_inventory(args: argparse.Namespace) -> int:
    plan = inventory.load_plan()
    planned_paths = {item["path"]: key for key, item in plan.items()}
    rows = inventory.live_repos(args.days)
    for row in rows:
        key = planned_paths.get(row["path"])
        item = plan.get(key, {}) if key else {}
        status = "skip: " + item["skip"] if item.get("skip") else (f"plan -> {item['slug']}" if key else "NOT PLANNED")
        print(f"{row['slug']:<28} {row['commits']:>4} commits  {status}")
    print(f"Live repos ({args.days} days): {len(rows)}  Plan: {inventory.plan_path()}")
    return EXIT_OK


def _run_provision(args: argparse.Namespace, plan: Dict[str, Dict[str, Any]], keys_: List[str]) -> int:
    results, failed = [], 0
    for key in keys_:
        item = plan[key]
        try:
            res = provision.provision(
                Path(item["path"]), item["slug"], item.get("name", item["slug"]), item.get("mounts", []),
                locale=item.get("locale", "pl"), dry_run=args.dry_run, commit=not args.no_commit,
            )
            results.append(res.__dict__)
            print(f"{key:<22} {res.slug:<20} key {res.key_mask} {'reused' if res.key_reused else 'new'}"
                  f"  project {'created' if res.project_created else res.project_id[:8]}"
                  f"  mounts {len(res.mounts_changed)}  commit {res.commit or '-'}{'  DRY-RUN' if res.dry_run else ''}")
        except Exception as err:  # one bad repo must not stop the batch
            failed += 1
            results.append({"repo": key, "error": str(err)})
            print(f"{key:<22} FAIL {err}")
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return EXIT_FAIL if failed else EXIT_OK


def _run_verify(args: argparse.Namespace, plan: Dict[str, Dict[str, Any]], keys_: List[str]) -> int:
    rows, failed = [], 0
    for key in keys_:
        item = plan[key]
        entry = store.get(item["slug"])
        if not entry:
            rows.append({"repo": key, "slug": item["slug"], "key": "not provisioned"})
            failed += 1
            continue
        key_state = verify.probe_key(entry["key"])
        mounts = verify.mounts_with_block(Path(item["path"]), item.get("mounts", []))
        page = verify.page_serves_widget(item["url"], entry["key"]) if item.get("url") else None
        row = {"repo": key, "slug": item["slug"], "key": key_state, "mounts_ok": all(mounts.values()) if mounts else None,
               "page": page, "url": item.get("url", "")}
        failed += key_state != verify.KEY_ACCEPTED or row["mounts_ok"] is False
        rows.append(row)
        print(f"{key:<22} key {key_state:<9} mounts {str(row['mounts_ok']):<5} live page {page}  {row['url']}")
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    return EXIT_FAIL if failed else EXIT_OK


def main(args: argparse.Namespace) -> int:
    action = getattr(args, "feedby_action", None)
    if action == "inventory":
        return _run_inventory(args)
    if action not in ("provision", "verify"):
        print("usage: jit feedby {inventory|provision|verify} ...")
        return EXIT_USAGE
    plan = inventory.load_plan()
    keys_ = _selected(args, plan)
    if not keys_:
        print(f"jit feedby {action}: no repos selected (give a plan key or --live). Plan: {inventory.plan_path()}")
        return EXIT_USAGE
    return _run_provision(args, plan, keys_) if action == "provision" else _run_verify(args, plan, keys_)
