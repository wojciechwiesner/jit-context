"""Data model for the suggestions engine: evidence, suggestions, the "missing input" signal and the project context.

A rule reads everything through ProjectContext (git, tracked files, STATE.md, usage view), so each git call or
file read happens once per evaluation and tests can point a context at a tmp repo with a fixed clock.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any, List, Optional, Tuple

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}
EVIDENCE_FILE = "file"
EVIDENCE_COMMAND = "command"
EVIDENCE_VALUE = "value"
GIT_TIMEOUT_SECONDS = 10
STATE_FILE = ".planning/STATE.md"
SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class Evidence:
    kind: str  # EVIDENCE_FILE | EVIDENCE_COMMAND | EVIDENCE_VALUE
    ref: str  # repo-relative path, command line or metric name
    value: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "value": self.value}


def file_evidence(path: str, value: str) -> Evidence:
    return Evidence(EVIDENCE_FILE, path, value)


def command_evidence(command: str, value: str) -> Evidence:
    return Evidence(EVIDENCE_COMMAND, command, value)


def value_evidence(name: str, value: Any) -> Evidence:
    return Evidence(EVIDENCE_VALUE, name, str(value))


@dataclass(frozen=True)
class Suggestion:
    rule_id: str
    severity: str
    summary: str  # Polish, what was found
    action: str  # Polish, the one recommended action
    evidence: Tuple[Evidence, ...]

    def to_dict(self) -> dict:
        return {"id": self.rule_id, "severity": self.severity, "summary": self.summary, "action": self.action,
                "evidence": [item.to_dict() for item in self.evidence]}


class MissingData(Exception):
    """The rule's input does not exist; the engine reports it as skipped with this (Polish) reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class ProjectContext:
    """Lazy, cached view of one project for the rules."""

    def __init__(self, path: Path, now: Optional[datetime] = None, usage: Any = None,
                 usage_missing: Optional[str] = None, usage_error: Optional[str] = None) -> None:
        self.path = Path(path)
        self.now = now or datetime.now()
        self._usage = usage
        self._usage_missing = usage_missing
        self._usage_error = usage_error

    def git(self, *args: str) -> Optional[str]:
        """stdout of a git command in the project, None on any failure."""
        try:
            result = subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True,
                                    timeout=GIT_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.returncode == 0 else None

    def read(self, rel_path: str) -> Optional[str]:
        try:
            return (self.path / rel_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    @cached_property
    def tracked_files(self) -> List[str]:
        out = self.git("ls-files", "-z")
        if out is None:
            raise MissingData("git ls-files nie działa (to nie jest repozytorium git?)")
        return [name for name in out.split("\0") if name]

    @cached_property
    def state_text(self) -> Optional[str]:
        return self.read(STATE_FILE)

    def require_state(self) -> str:
        if self.state_text is None:
            raise MissingData(f"brak {STATE_FILE}")
        return self.state_text

    @cached_property
    def newest_commit(self) -> Optional[Tuple[int, str, str]]:
        """(commit time, short sha, subject) of the newest commit on any local branch or HEAD."""
        out = self.git("log", "--branches", "HEAD", "-1", "--format=%ct%x00%h%x00%s")
        if not out or not out.strip():
            return None
        ts, sha, subject = (out.strip().split("\0") + ["", ""])[:3]
        return int(ts), sha, subject

    def require_newest_commit(self) -> Tuple[int, str, str]:
        if self.newest_commit is None:
            raise MissingData("brak commitów w repozytorium")
        return self.newest_commit

    def usage_view(self) -> Any:
        if self._usage_error is not None:
            raise RuntimeError(self._usage_error)
        if self._usage is None:
            raise MissingData(self._usage_missing or "brak danych zużycia (usage.sqlite)")
        return self._usage
