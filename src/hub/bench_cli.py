"""CLI for `jit bench ab <project> [--tasks file] [--runs 3] [--model sonnet] [--yes]`.

Without --yes nothing runs: the plan and the estimated number of model calls are printed and the exit code is 2.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from hub import bench, bench_store, registry
from hub.bench_tasks import BenchTask, TaskFileError, default_tasks, load_task_file
from hub.gitinfo import resolve_repo

EXIT_USAGE = 2
EXIT_FAILED = 1
DEFAULT_RUNS = 3
DEFAULT_MODEL = "sonnet"
PROMPT_PREVIEW_CHARS = 100
MISSING = "brak"
METRIC_LABELS = (("total_tokens", "tokeny łącznie"), ("num_turns", "tury"), ("wall_s", "czas [s]"),
                 ("cost_usd", "koszt [USD]"))
LABEL_WIDTH = 16
COLUMN_WIDTH = 22


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="bench_action")
    ab = actions.add_parser("ab", help="Controlled A/B: claude -p with JIT on vs off in temporary worktrees")
    ab.add_argument("project", help="Registered project slug or project path")
    ab.add_argument("--tasks", default=None, help="Task file: JSON list or one prompt per line (default: "
                                                  "3 questions from STATE.md open tasks and README)")
    ab.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="Repetitions per task (default 3)")
    ab.add_argument("--model", default=DEFAULT_MODEL, help="Model for claude --model (default sonnet)")
    ab.add_argument("--yes", action="store_true", help="Really run (costs tokens)")


def resolve_project(value: str) -> Optional[Tuple[str, Path]]:
    """(slug, main repo path) for a registry slug or a git directory; None when neither."""
    entries = registry.load_projects()
    for entry in entries:
        if entry["slug"] == value:
            return entry["slug"], Path(entry["path"])
    path = Path(value).expanduser()
    if not path.is_dir():
        return None
    identity = resolve_repo(path)
    if identity.git_common_dir is None:
        return None
    for entry in entries:
        if Path(entry["path"]).resolve() == identity.main_path:
            return entry["slug"], identity.main_path
    return identity.main_path.name, identity.main_path


def _load_tasks(args: argparse.Namespace, repo: Path) -> List[BenchTask]:
    if args.tasks:
        return load_task_file(Path(args.tasks).expanduser())
    return default_tasks(repo)


def _print_plan(slug: str, repo: Path, tasks: List[BenchTask], args: argparse.Namespace) -> None:
    print(f"A/B kontrolowany: projekt {slug}  repo {repo}  model {args.model}  powtórzenia {args.runs}")
    for task in tasks:
        print(f"  [{task.task_id}] {task.prompt[:PROMPT_PREVIEW_CHARS]}")
    calls = bench.estimated_calls(len(tasks), args.runs)
    print(f"Szacowana liczba wywołań modelu: {calls} ({len(tasks)} zadań x {args.runs} powtórzeń x 2 ramiona)")


def _fmt(cell: dict) -> str:
    value = cell["median"]
    if value is None:
        return f"{MISSING} (n=0)"
    small_fraction = isinstance(value, float) and 0 < abs(value) < 1
    text = f"{value:.4f}" if small_fraction else f"{value:,.1f}".rstrip("0").rstrip(".")
    return f"{text} (n={cell['n']})"


def render_summary(batch_id: str, summary: dict) -> str:
    arms, paired = summary["arms"], summary["paired_on_minus_off"]
    lines = [
        f"Wynik {batch_id}: wywołań {summary['calls']}, błędy JIT on {arms['on']['errors']}, "
        f"JIT off {arms['off']['errors']}",
        f"{'mediana':<{LABEL_WIDTH}}{'JIT on':<{COLUMN_WIDTH}}{'JIT off':<{COLUMN_WIDTH}}różnica w parach (on - off)",
    ]
    for key, label in METRIC_LABELS:
        lines.append(f"{label:<{LABEL_WIDTH}}{_fmt(arms['on'][key]):<{COLUMN_WIDTH}}"
                     f"{_fmt(arms['off'][key]):<{COLUMN_WIDTH}}{_fmt(paired[key])}")
    return "\n".join(lines)


def _print_progress(row: dict) -> None:
    tokens = bench_store.total_tokens(row)
    state = f"BŁĄD {row.get('error')}" if row.get("is_error") else "ok"
    print(f"  {row['task_id']} r{row['run_index']} JIT {row['arm']:<3}  {state}  tokeny "
          f"{MISSING if tokens is None else tokens}  tury {row.get('num_turns') or MISSING}  "
          f"czas {row['wall_s']} s", flush=True)


def _run_ab(args: argparse.Namespace) -> int:
    resolved = resolve_project(args.project)
    if resolved is None:
        print(f"jit bench ab: nieznany projekt (ani slug z rejestru, ani repozytorium git): {args.project}")
        return EXIT_USAGE
    if args.runs <= 0:
        print("jit bench ab: --runs musi być większe od zera")
        return EXIT_USAGE
    slug, repo = resolved
    try:
        tasks = _load_tasks(args, repo)
    except TaskFileError as exc:
        print(f"jit bench ab: --tasks: {exc}")
        return EXIT_USAGE
    if not tasks:
        print(f"jit bench ab: brak otwartych zadań w .planning/STATE.md i brak README w {repo}; podaj --tasks")
        return EXIT_USAGE
    _print_plan(slug, repo, tasks, args)
    if not args.yes:
        print("Nic nie uruchomiono. Każde wywołanie kosztuje tokeny; dodaj --yes, aby wykonać.")
        return EXIT_USAGE
    if shutil.which(bench.CLAUDE_BIN) is None:
        print(f"jit bench ab: nie znaleziono '{bench.CLAUDE_BIN}' w PATH")
        return EXIT_FAILED
    spec = bench.BenchSpec(project=slug, repo=repo, tasks=tasks, runs=args.runs, model=args.model)
    conn = bench_store.connect()
    try:
        batch_id = bench.run_batch(spec, conn, _print_progress)
        rows = bench_store.read_batch(conn, batch_id)
    except bench.BenchError as exc:
        print(f"jit bench ab: przerwano: {exc}")
        return EXIT_FAILED
    finally:
        conn.close()
    print(render_summary(batch_id, bench_store.summarize(rows)))
    print(f"Zapisano w {bench_store.usage_store.usage_db_path()} (tabela ab_runs, batch_id {batch_id})")
    return EXIT_FAILED if any(row["is_error"] for row in rows) else 0


def main(args: argparse.Namespace) -> int:
    if getattr(args, "bench_action", None) == "ab":
        return _run_ab(args)
    print("Użycie: jit bench ab <projekt> [--tasks plik] [--runs 3] [--model sonnet] [--yes]")
    return EXIT_USAGE
