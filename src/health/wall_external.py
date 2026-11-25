"""Operator Wall: sources that need a subprocess (Hermes kanban, worker-dispatch). Cached, bounded, read-only."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from health.wall_readers import HERMES_HOME

KANBAN_CACHE_S = 120.0
NODES_CACHE_S = 300.0
KANBAN_TIMEOUT_S = 15
NODES_TIMEOUT_S = 20
KANBAN_WORKERS = 6
EXTRA_PATH = (str(HERMES_HOME / "hermes-agent" / ".hermes" / "bin"), "/opt/homebrew/bin",
              str(Path.home() / ".local" / "bin"))

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_refreshing: set[str] = set()


def _key_lock(key: str) -> threading.Lock:
    with _lock:
        return _key_locks.setdefault(key, threading.Lock())


def _store(key: str, build: Callable[[], Any]) -> tuple[Any, float]:
    with _key_lock(key):  # one build per key at a time (prewarm and the API call must not both spawn it)
        value = build()
        with _lock:
            _cache[key] = (time.time(), value)
    return value, 0.0


def _refresh_quietly(key: str, build: Callable[[], Any]) -> None:
    try:
        _store(key, build)
    except Exception:
        return  # keep serving the stale value; its growing age_s is visible on the wall
    finally:
        with _lock:
            _refreshing.discard(key)


def cached(key: str, ttl: float, build: Callable[[], Any]) -> tuple[Any, float]:
    """(value, age_s). Stale values are served at once while a background thread refreshes them.

    The very first call blocks (nothing to serve yet); a failing first call is not cached and re-raises.
    """
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        stale = bool(hit) and now - hit[0] >= ttl
        start_refresh = stale and key not in _refreshing
        if start_refresh:
            _refreshing.add(key)
    if hit is None:
        return _store(key, build)
    if start_refresh:
        threading.Thread(target=_refresh_quietly, args=(key, build), daemon=True).start()
    return hit[1], now - hit[0]


def _fill(fn: Callable[[], Any]) -> None:
    try:
        fn()
    except Exception:
        return  # the API call reports the failure as "brak danych"


def prewarm() -> None:
    """Fill the slow caches in the background (called when the wall page is opened)."""
    for fn in (blocked_cards, nodes):
        threading.Thread(target=_fill, args=(fn,), daemon=True).start()


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _refreshing.clear()


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([*EXTRA_PATH, env.get("PATH", "")])
    return env


def run(args: list[str], timeout: int) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env(), check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{args[0]} exit {done.returncode}: {done.stderr.strip()[:120]}")
    return done.stdout


def _blocked_on_board(slug: str) -> list[dict[str, Any]]:
    out = run(["hermes", "kanban", "--board", slug, "list", "--status", "blocked", "--json"], KANBAN_TIMEOUT_S)
    return [{"id": c.get("id"), "title": c.get("title") or "", "board": slug,
             "since": float(c.get("created_at") or 0)} for c in json.loads(out)]


def _read_kanban() -> list[dict[str, Any]]:
    boards = json.loads(run(["hermes", "kanban", "boards", "list", "--json"], KANBAN_TIMEOUT_S))
    slugs = [b["slug"] for b in boards if b.get("slug") and (b.get("counts") or {}).get("blocked")]
    with ThreadPoolExecutor(max_workers=KANBAN_WORKERS) as pool:
        groups = list(pool.map(_blocked_on_board, slugs))
    return sorted((card for group in groups for card in group), key=lambda c: c["since"])


def blocked_cards() -> tuple[list[dict[str, Any]], float]:
    return cached("kanban", KANBAN_CACHE_S, _read_kanban)


def parse_nodes(text: str) -> list[dict[str, Any]]:
    """`worker-dispatch status` lines look like `omarchy: ONLINE claude-auth=unknown`."""
    nodes = []
    for line in text.splitlines():
        name, sep, rest = line.partition(":")
        if not sep or not name.strip() or " " in name.strip():
            continue
        state = rest.strip().split(" ", 1)
        nodes.append({"name": name.strip(), "online": state[0].upper() == "ONLINE",
                      "detail": state[1].strip() if len(state) > 1 else ""})
    return nodes


def _read_nodes() -> list[dict[str, Any]]:
    script = HERMES_HOME / "bin" / "worker-dispatch"
    return parse_nodes(run([str(script), "status"], NODES_TIMEOUT_S))


def nodes() -> tuple[list[dict[str, Any]], float]:
    return cached("nodes", NODES_CACHE_S, _read_nodes)
