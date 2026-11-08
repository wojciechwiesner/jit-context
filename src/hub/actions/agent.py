"""One headless agent process for a hub action: `claude -p` (or $JIT_HUB_AGENT_CMD) with read-only tools.

The prompt goes to stdin (the tool options take variable argument lists, so a positional prompt after them would
be swallowed). The agent prints one JSON result (`--output-format json`); anything else is a failure with the
reason, never a made-up report.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

AGENT_CMD_ENV = "JIT_HUB_AGENT_CMD"
DEFAULT_AGENT_CMD = "claude"
EXTRA_BIN_DIRS = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin")
AVAILABLE_TOOLS = ("Read", "Grep", "Glob", "WebSearch", "WebFetch", "Bash")
ALLOWED_TOOLS = ("Read", "Grep", "Glob", "WebSearch", "WebFetch",
                 "Bash(git log:*)", "Bash(git status:*)", "Bash(ls:*)")
DENIED_TOOLS = ("Edit", "Write", "NotebookEdit")
RUN_TIMEOUT_SECONDS = 30 * 60
KILL_WAIT_SECONDS = 5
OUTPUT_TAIL_CHARS = 2000

SUCCEEDED = "succeeded"
FAILED = "failed"
TIMEOUT = "timeout"


@dataclass
class AgentResult:
    status: str
    report: Optional[str] = None
    error: Optional[str] = None
    returncode: Optional[int] = None
    usage: Optional[dict] = None
    cost: Optional[float] = None
    details: dict = field(default_factory=dict)


def resolve_executable(name: str) -> str:
    """Absolute path of `name` from PATH or the usual per-user install dirs, else `name` unchanged.

    Mission Control runs under launchd with PATH=/usr/bin:/bin:/usr/sbin:/sbin, where the user-installed
    `claude` (~/.local/bin) is invisible; without this the hub actions fail with Errno 2."""
    if os.sep in name:
        return name
    search = os.pathsep.join([os.environ.get("PATH", ""),
                              *(str(Path(d).expanduser()) for d in EXTRA_BIN_DIRS)])
    return shutil.which(name, path=search) or name


def agent_command() -> List[str]:
    """Executable from $JIT_HUB_AGENT_CMD (shell-split) or `claude`, plus the fixed read-only options."""
    raw = os.environ.get(AGENT_CMD_ENV, "").strip()
    base = shlex.split(raw) if raw else [DEFAULT_AGENT_CMD]
    return [resolve_executable(base[0]), *base[1:]] + [
        "-p", "--output-format", "json",
        "--restricted", "--strict-mcp-config", "--no-session-persistence",
        "--permission-mode", "dontAsk",
        "--tools", ",".join(AVAILABLE_TOOLS),
        "--allowedTools", ",".join(ALLOWED_TOOLS),
        "--disallowedTools", ",".join(DENIED_TOOLS),
    ]


def _tail(text: str) -> str:
    text = (text or "").strip()
    return text[-OUTPUT_TAIL_CHARS:]


def _result_object(payload):
    """The result object: newer Claude Code prints the whole event list for `--output-format json`
    (system/assistant/.../result); older ones print only the final result object."""
    if isinstance(payload, list):
        results = [item for item in payload if isinstance(item, dict) and item.get("type") == "result"]
        return results[-1] if results else None
    return payload if isinstance(payload, dict) else None


def parse_output(stdout: str) -> AgentResult:
    """AgentResult from the `--output-format json` result object (or event list ending in one)."""
    try:
        payload = _result_object(json.loads(stdout))
    except ValueError:
        return AgentResult(FAILED, error=f"agent nie zwrócił JSON: {_tail(stdout) or '(pusty wynik)'}")
    if payload is None:
        return AgentResult(FAILED, error="agent zwrócił JSON, ale nie obiekt wyniku")
    cost = payload.get("total_cost_usd")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    details = {key: payload.get(key) for key in ("subtype", "num_turns", "duration_ms", "session_id")
               if key in payload}
    result = payload.get("result")
    if payload.get("is_error") or payload.get("subtype", "success") != "success":
        reason = result if isinstance(result, str) and result.strip() else payload.get("subtype")
        return AgentResult(FAILED, error=f"agent zakończył się błędem: {reason}", usage=usage,
                           cost=cost, details=details)
    if not isinstance(result, str) or not result.strip():
        return AgentResult(FAILED, error="agent nie zwrócił treści raportu", usage=usage, cost=cost,
                           details=details)
    return AgentResult(SUCCEEDED, report=result, usage=usage, cost=cost, details=details)


def _kill(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()


def run_agent(prompt: str, cwd: Path, timeout: float = RUN_TIMEOUT_SECONDS) -> AgentResult:
    """Run the agent in `cwd` with the prompt on stdin; kill its whole process group on timeout."""
    command = agent_command()
    try:
        process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                   start_new_session=True)
    except OSError as exc:
        return AgentResult(FAILED, error=f"nie można uruchomić agenta {command[0]!r}: {exc}")
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(process)
        try:
            process.communicate(timeout=KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return AgentResult(TIMEOUT, error=f"przekroczono limit czasu {timeout:g} s; proces agenta zatrzymany",
                           returncode=process.returncode)
    if process.returncode != 0:
        parsed = parse_output(stdout)
        parts = [part for part in (_tail(stderr), parsed.error if stdout.strip() else None) if part]
        detail = "; ".join(parts) or "(brak stderr)"
        return AgentResult(FAILED, error=f"agent zakończył się kodem {process.returncode}: {detail}",
                           returncode=process.returncode, usage=parsed.usage, cost=parsed.cost,
                           details=parsed.details)
    result = parse_output(stdout)
    result.returncode = process.returncode
    return result
