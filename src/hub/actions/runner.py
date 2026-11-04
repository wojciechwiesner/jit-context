"""Queue of hub action runs: at most MAX_CONCURRENT_RUNS agents at once, the rest wait in FIFO order.

submit() writes the run state (status queued) and returns at once; a daemon worker thread later marks it
running, runs the agent (hub.actions.agent) in the project directory and records the outcome: succeeded with
the report path, or failed / timeout with the error. Workers are daemon threads, so a server shutdown never
waits 30 minutes; runs cut off that way are reported as interrupted by run_store.list_runs.
"""

from __future__ import annotations

import os
import queue
import threading
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from hub import actions
from hub.actions import agent, report, run_store

MAX_CONCURRENT_RUNS = 2

AgentFn = Callable[[str, Path, float], agent.AgentResult]


class ActionBusy(RuntimeError):
    """The same action is already queued or running for this project."""


class Runner:
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_RUNS,
                 timeout: float = agent.RUN_TIMEOUT_SECONDS, agent_fn: AgentFn = agent.run_agent) -> None:
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._agent_fn = agent_fn
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._submit_lock = threading.Lock()
        self._workers_started = False

    def _start_workers(self) -> None:
        if self._workers_started:
            return
        for number in range(self.max_concurrent):
            threading.Thread(target=self._work, name=f"jit-hub-action-{number}", daemon=True).start()
        self._workers_started = True

    def submit(self, entry: dict, action: str) -> dict:
        """Queue one run of `action` for a registry entry; ActionBusy when that pair is already active."""
        if action not in actions.ACTION_LABELS:
            raise ValueError(f"unknown action: {action!r}")
        with self._submit_lock:
            if run_store.active_run(entry["slug"], action) is not None:
                raise ActionBusy(f"{actions.ACTION_LABELS[action]} dla {entry['slug']} już czeka lub trwa")
            run = run_store.save({
                "id": run_store.new_run_id(action), "slug": entry["slug"], "action": action,
                "label": actions.ACTION_LABELS[action], "project_path": entry["path"],
                "status": run_store.QUEUED, "created": run_store.now_iso(), "started": None, "finished": None,
                "usage": None, "cost": None, "report_path": None, "obsidian_path": None, "error": None,
                "server_pid": os.getpid(), "timeout_seconds": self.timeout,
            })
            self._start_workers()
            self._queue.put(run["id"])
        return run

    def _work(self) -> None:
        while True:
            run_id = self._queue.get()
            try:
                self.execute(run_id)
            except Exception as exc:  # a broken run must not kill the worker; record the real error
                run_store.update(run_id, status=agent.FAILED, finished=run_store.now_iso(),
                                 error=f"błąd wewnętrzny runnera: {type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()

    def execute(self, run_id: str) -> dict:
        """Run one queued run to the end (called by the workers) and return its final state."""
        run = run_store.load(run_id)
        if run is None:
            raise FileNotFoundError(f"run state missing: {run_id}")
        run = run_store.update(run_id, status=run_store.RUNNING, started=run_store.now_iso())
        project = Path(run["project_path"])
        if not project.is_dir():
            return run_store.update(run_id, status=agent.FAILED, finished=run_store.now_iso(),
                                    error=f"katalog projektu nie istnieje: {project}")
        day = date.today().isoformat()
        prompt = actions.render_prompt(run["action"], run["slug"], str(project), day)
        result = self._agent_fn(prompt, project, self.timeout)
        fields = {"status": result.status, "finished": run_store.now_iso(), "usage": result.usage,
                  "cost": result.cost, "error": result.error, "returncode": result.returncode,
                  "agent": result.details}
        if result.status == agent.SUCCEEDED:
            fields.update(report.save_report(dict(run, **fields), result.report or "", day))
        return run_store.update(run_id, **fields)

    def wait_idle(self) -> None:
        """Block until every submitted run is finished (tests, shutdown scripts)."""
        self._queue.join()


_DEFAULT: Optional[Runner] = None
_DEFAULT_LOCK = threading.Lock()


def default_runner() -> Runner:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = Runner()
        return _DEFAULT


def set_default_runner(runner: Optional[Runner]) -> None:
    """Swap the process-wide runner (tests use a short timeout or a smaller limit)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = runner
