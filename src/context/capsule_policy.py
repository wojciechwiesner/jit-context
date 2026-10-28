"""Ground inferred targets and preserve capsule metadata across host boundaries."""

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

HOST_CAPSULE_MAX_CHARS = 14000
CLOSING_TAG = "</ONA_CONTEXT>"
RELOAD_NOTICE = re.compile(r"\A\s*\[IMPORTANT: MCP servers have been reloaded\.[^\]]*\]\s*", re.S)
NOTIFICATION = re.compile(
    r"\A\s*(?:\[ASYNC DELEGATION|\[IMPORTANT:\s*(?:Background process\b|"
    r"\d+ background processes completed\b|MCP servers have been reloaded\.))",
    re.I,
)


def strip_reload_notices(text: str) -> str:
    """Remove only known host notices, preserving a following real user request."""
    while RELOAD_NOTICE.match(text):
        text = RELOAD_NOTICE.sub("", text, count=1)
    return text.strip()


def is_host_notification(text: str) -> bool:
    return bool(NOTIFICATION.match(text or ""))


def extract_genuine_user_instruction(text: str) -> str:
    """Extract real human instruction if message is wrapped in a skill invocation or harness prefix."""
    text = strip_reload_notices(text or "")
    if is_host_notification(text):
        return ""
    if not text:
        return ""
    # Strip nested/quoted <ONA_CONTEXT ...> blocks to avoid self-poisoning
    clean = re.sub(r'<ONA_CONTEXT.*?</ONA_CONTEXT>', '', text, flags=re.DOTALL).strip()
    if clean:
        text = clean
    # Strip injected ENGINEERING CANON
    clean = re.sub(r'\n*ENGINEERING CANON \(~.*', '', text, flags=re.DOTALL).strip()
    if clean:
        text = clean
    m = re.search(r"The user has provided the following instruction alongside the skill invocation:\s*(.*)", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text

def is_synthetic_harness_message(text: str) -> bool:
    """Detect internal Hermes harness prompts (curator, delegation, /btw, canon)."""
    if not text:
        return False
    if is_host_notification(text):
        return True
    t = text.strip()
    prefixes = (
        "[ASYNC DELEGATION",
        "Review the conversation above and update the skill library",
        "The user asked a quick SIDE question with /btw",
        "[OUT-OF-BAND USER MESSAGE",
        "ENGINEERING CANON (~",
        "<ONA_CONTEXT",
        "[ONA_CONTEXT",
        "[IMPORTANT: The user has invoked the ",
        # Host notifications (background process completion, system reminders) are not
        # user instructions and must never enter [PRIOR USER INSTRUCTIONS].
        "[IMPORTANT: Background process",
        "[SYSTEM:",
        "<system-reminder>",
    )
    return any(t.startswith(p) for p in prefixes)


def unpack_compilation(result: Any) -> Tuple[str, Dict[str, Any]]:
    """CapsuleResult is a str subclass, not a tuple; do not discard its metadata."""
    if isinstance(getattr(result, "meta", None), dict):
        return str(result), dict(result.meta)
    if isinstance(result, tuple) and len(result) == 2:
        capsule, meta = result
        return str(capsule), dict(meta) if isinstance(meta, dict) else {}
    return str(result), {}


def working_set_paths(capsule: str) -> List[str]:
    matches = re.findall(
        r"• ([^\n(]+?) \((?:active module|written|read_ok|\d+ lines)\)", capsule,
    )
    return list(dict.fromkeys(path.strip() for path in matches))


def selected_targets(goal: str, candidates: List[str], runtime: Dict[str, Any]) -> List[str]:
    """Historical working sets alone cannot authorize targets for a new task."""
    root_text = runtime.get("cwd") or runtime.get("working_directory")
    root = Path(root_text).resolve() if root_text else None
    selected = []
    for value in candidates:
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        explicit_absolute = path.is_absolute() and value in goal
        if root and not explicit_absolute:
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root):
                continue
        mentioned = re.search(r"(?<![\w.-])" + re.escape(path.name) + r"(?![\w.-])", goal)
        if explicit_absolute or mentioned:
            selected.append(value)
    return list(dict.fromkeys(selected))[:10]


def finalize_capsule(capsule: str, meta: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Apply the independent host limit after ALL enrichments, keeping a valid close."""
    meta = dict(meta)
    budget = min(int(meta.get("budget") or HOST_CAPSULE_MAX_CHARS), HOST_CAPSULE_MAX_CHARS)
    meta["assembler_budget"] = meta.get("budget")
    meta["budget"] = budget
    body, separator, tail = str(capsule).partition(CLOSING_TAG)
    if tail.strip():
        body += "\n  [RUNTIME STATUS — advisory]\n" + tail.strip()
    suffix = "\n" + CLOSING_TAG
    if len(body) + len(suffix) > budget:
        marker = "\n[...truncated to host capsule budget]"
        body = body[:max(0, budget - len(suffix) - len(marker))] + marker
        meta["host_truncated"] = True
    else:
        meta["host_truncated"] = False
    return body.rstrip() + suffix, meta


def path_in_active_workspace(path: Path, root_text: str, goal: str) -> bool:
    if not root_text:
        return True
    if path.is_absolute() and str(path) in goal:
        return True
    root = Path(root_text).resolve()
    return (root / path).resolve().is_relative_to(root)
