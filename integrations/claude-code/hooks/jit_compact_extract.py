"""Deterministic extraction of the essentials from a Claude Code transcript segment.

Used by jit-compact-hook.py right before Claude Code compacts a conversation. It reads
the rows since the last compact boundary and keeps what a continuation needs:
user instructions, question -> final answer exchanges, files changed, and tool
evidence lines (test results, commits, HTTP codes, verification output). Everything
else (raw tool dumps, exploratory reads, intermediate chatter) stays in the transcript.
"""
from __future__ import annotations

import json
import re

PROMPT_CHARS = 280
ANSWER_CHARS = 1400
EVIDENCE_LINE_CHARS = 220
EVIDENCE_LINES_PER_CALL = 3
ANSWER_MIN_CHARS = 80
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SIGNAL_RE = re.compile(
    r"(\b\d+ (passed|failed|errors?)\b|\bFAILED\b|\bTraceback\b|\b(Error|ERROR)\b:|HTTP/[\d.]+ \d{3}"
    r"|\bstatus[ =:]+\d{3}\b|^\[[\w/.-]+ [0-9a-f]{7,}\]|\b[Ee]xit(ed)?( code)?[ =:]+\d+"
    r"|\bset: |\b[Vv]erified\b|\bOK\b|\bPASS(ED)?\b)",
    re.MULTILINE,
)
# Lines echoed from earlier essentials/capsules (evidence about evidence), not new proofs.
ECHO_RE = re.compile(r"^(- Bash:|E: |• \[|\[Bash:|<JIT_|<ONA_)")
# Commands that read the compaction machinery itself produce self-referential output.
META_COMMAND_RE = re.compile(r"jit_compact|jit-compact-hook|ona_context_|session_overlay")


def load_segment(transcript_path: str) -> tuple[list[dict], int]:
    """Rows after the last compact boundary, plus the index of the first returned row."""
    rows = []
    with open(transcript_path, encoding="utf-8") as fh:
        for raw in fh:
            try:
                rows.append(json.loads(raw))
            except ValueError:
                continue
    start = 0
    for i, row in enumerate(rows):
        if row.get("subtype") == "compact_boundary":
            start = i + 1
    return rows[start:], start


def _blocks(row: dict) -> list:
    content = (row.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _user_prompt(row: dict) -> str:
    if row.get("type") != "user" or row.get("isMeta") or row.get("isCompactSummary"):
        return ""
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    text = content.strip() if isinstance(content, str) else ""
    return "" if text.startswith("<") else text


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


def _signal_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and SIGNAL_RE.search(ln) and not ECHO_RE.match(ln.strip())]
    return [ln[:EVIDENCE_LINE_CHARS] for ln in lines[-EVIDENCE_LINES_PER_CALL:]]


def extract(rows: list[dict]) -> dict:
    """Return {'prompts', 'exchanges', 'files', 'evidence', 'errors'} from transcript rows."""
    prompts, exchanges, files, evidence, errors = [], [], [], [], []
    pending_calls: dict[str, dict] = {}
    current = None
    for row in rows:
        prompt = _user_prompt(row)
        if prompt:
            prompts.append(prompt[:PROMPT_CHARS])
            current = {"prompt": prompt[:PROMPT_CHARS], "answer": ""}
            exchanges.append(current)
            continue
        for block in _blocks(row):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and row.get("type") == "assistant" and current is not None:
                text = block.get("text", "").strip()
                if len(text) >= ANSWER_MIN_CHARS:
                    current["answer"] = text[:ANSWER_CHARS]
            elif kind == "tool_use":
                pending_calls[block.get("id", "")] = block
                path = (block.get("input") or {}).get("file_path")
                if block.get("name") in EDIT_TOOLS and path and path not in files:
                    files.append(path)
            elif kind == "tool_result":
                _record_result(block, pending_calls, evidence, errors)
    exchanges = [e for e in exchanges if e["answer"]]
    return {"prompts": prompts, "exchanges": exchanges, "files": files,
            "evidence": evidence, "errors": errors}


def _record_result(block: dict, calls: dict, evidence: list, errors: list) -> None:
    call = calls.get(block.get("tool_use_id", ""), {})
    name = call.get("name", "tool")
    args = call.get("input") or {}
    label = args.get("description") or args.get("command") or args.get("file_path") or name
    text = _result_text(block)
    if block.get("is_error"):
        errors.append(f"{name}: {str(label)[:80]} -> {text.strip()[:160]}")
        return
    # MCP/WebFetch results are data, not verification; their "error"/"failed" lines are noise.
    if name != "Bash" or META_COMMAND_RE.search(str(args.get("command", ""))):
        return
    lines = _signal_lines(text)
    if lines:
        evidence.append({"key": f"{name}: {str(label)[:100]}", "value": " | ".join(lines)})
