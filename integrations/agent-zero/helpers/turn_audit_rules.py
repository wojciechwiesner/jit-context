"""Check catalog for the per-turn autochecker (turn_audit_rules.py).

Each check is deterministic and cheap. A failed check becomes a *finding*; findings are merged by key into the
jitjevmods.md backlog, so the same problem seen on 30 turns is one mod with count=30, not 30 lines.
Self-contained Agent Zero port.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional

# key: (title, component, severity, proposal)
CATALOG: Dict[str, tuple] = {
    "capsule_missing": ("No JIT capsule for this turn", "JIT L0 / pre_llm hook", "high",
                        "pre_llm_call did not produce a capsule for the turn; check hook registration and the fail-open path."),
    "capsule_goal_stale": ("Capsule goal does not match the user prompt", "JIT L0 goal extraction", "high",
                           "Capsule 'Goal' came from an older/synthetic message. Re-derive the goal from the genuine last user message on every turn."),
    "capsule_goal_truncated": ("Capsule goal truncates the user prompt", "JIT L0 goal extraction", "medium",
                               "Long prompts lose their tail requirements. Keep the full prompt (or a requirement list) in the capsule instead of a prefix."),
    "spec_missing": ("Coding turn without spec / acceptance criteria", "JIT L2 prompt enhancer", "medium",
                     "Files were edited but the capsule had no Enhanced Spec / Acceptance Criteria. Trigger the enhancer for build/fix intents."),
    "project_goal_absent": ("Capsule has no project-goal anchor", "JIT L1 project context", "medium",
                            "Inject the one-line Active Goal from .planning/STATE.md so each turn can be checked against the project direction."),
    "project_goal_offtrack": ("Prompt unrelated to the project Active Goal", ".planning/STATE.md", "low",
                              "Either STATE.md 'Active Goal' is stale or the session drifted. Update STATE.md when the focus changes."),
    "scope_split": ("Session state split across scopes", "JIT L1 scope hysteresis", "high",
                    "Session directories exist under multiple scopes (e.g. general and hermes). Hysteresis guard should keep a session bound to one scope."),
    "targets_untouched": ("Target files in spec never edited", "JIT L2 prompt enhancer", "low",
                          "Capsule listed Target Files but none of them was touched. Check if enhancer picked wrong targets or agent solved it elsewhere."),
    "claim_without_proof": ("Assistant claimed success without verification", "JEV shadow judge", "high",
                            "Assistant replied with claims like 'działa'/'works'/'all tests pass' but no verify tool (terminal/execute_code/browser) was called."),
    "edit_not_verified": ("Code edited without follow-up test/run", "JEV harness", "medium",
                          "Source code was written/patched after the last verification tool ran. Always run tests/syntax check after the last edit."),
    "reply_language": ("Reply language drifted from prompt", "JEV / Persona", "low",
                       "User prompted in Polish but assistant answered in English. Keep the assistant language matched to the user's turn."),
    "tool_error_rate": ("Excessive tool failures on turn", "Harness / tool contracts", "high",
                        "More than 25% of tool calls on this turn failed. Check parameter formats and pre-flight validation."),
    "reread_same_file": ("Same file read 3+ times in one turn", "Harness / caching", "medium",
                         "The same path was read repeatedly. Keep read_file results in context or use targeted offsets instead of re-reading from line 1."),
    "duplicate_calls": ("Repeated identical tool call", "Harness / loop guard", "medium",
                        "The exact same tool call (same name and arguments) ran more than once on this turn. Harness loop guard should suppress or warn."),
    "truncation_refetch": ("Refetching right after a truncated output", "Harness / truncation window", "low",
                           "A truncated tool output was immediately re-fetched. Increase char budget or use targeted sub-queries instead."),
    "stale_write_blocked": ("write_file refused on stale content", "Harness / tool contracts", "medium",
                            "write_file refused to overwrite because file changed or was unread. Read before writing, or use patch for surgical edits."),
    "long_turn": ("Turn exceeded tool-count or time budget", "Harness / latency", "low",
                  "Turn ran >40 tool calls or >20 minutes. Break the task down into sub-goals."),
    "hook_latency": ("Pre-LLM hook latency exceeded budget", "JIT L0 hook", "medium",
                     "Combined hook latency exceeded 600ms budget. Move heavy reads out of pre_llm into background or L2 warm path."),
    "capsule_over_budget": ("Capsule tokens exceeded target budget", "JIT capsule compiler", "medium",
                            "Capsule exceeded 1800 estimated tokens. Trim low-authority dynamic facts or lower L2 fact cap."),
    "telemetry_degraded": ("Turn telemetry reported invariant failures", "JIT invariants", "high",
                           "Turn telemetry flagged degraded=True or failed invariants. Inspect telemetry row for which invariant tripped."),
}

STOP = set("a i w z na do to że się nie jak co czy po tak ten ta the and of to in is for on with that this it be are".split())
PL_WORDS = re.compile(r"\b(jest|nie|się|oraz|żeby|czy|jak|dla|teraz|zrób|zrob|sprawdz|sprawdź|działa|dzialal|gotowe|tak|też|tez)\b", re.I)
PL_CHARS = re.compile(r"[ąćęłńóśźż]", re.I)

VERIFY_TOOLS = {
    "terminal", "execute_code", "code_execution_tool", "run_command", "bash",
    "browser_exec", "browser", "vision_analyze", "vision_load"
}
CODE_EXT = re.compile(r"\.(py|js|ts|jsx|tsx|rs|go|c|cpp|h|java|rb|php|sh|html|css|json|yaml|yml|toml)$")
TRUNC_MARKERS = ("truncated", "head+tail", "Output exceeded", "characters omitted", "OUTPUT TRUNCATED")

SEVERITY_WEIGHT = {"high": 25, "medium": 10, "low": 4}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def finding(key: str, evidence: str) -> Dict[str, Any]:
    title, component, severity, proposal = CATALOG[key]
    return {"key": key, "title": title, "component": component, "severity": severity, "proposal": proposal, "evidence": evidence}


def words(text: str) -> set:
    return {w for w in re.findall(r"[a-ząćęłńóśźż0-9_]{3,}", (text or "").lower()) if w not in STOP}


def overlap(a: str, b: str) -> float:
    """Share of `a`'s content words present in `b` (asymmetric containment)."""
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa) if wa else 1.0


def is_polish(text: str) -> bool:
    return bool(PL_CHARS.search(text or "")) or len(PL_WORDS.findall(text or "")) >= 2


def is_error(result: str, error_flag: Optional[bool] = None) -> bool:
    if error_flag is True:
        return True
    if not result:
        return False
    head = str(result)[:800]
    if re.search(r'"error":\s*"[^"]', head) or re.search(r'"exit_code":\s*[1-9]', head):
        return True
    return head.lstrip().startswith(("Error", "Traceback")) or '"success": false' in head


def project_goal(cwd: Optional[str]) -> str:
    """First line under '## Active Goal' in <repo>/.planning/STATE.md (walks up to the git root)."""
    p = Path(cwd) if cwd else None
    while p and p != p.parent:
        state = p / ".planning" / "STATE.md"
        if state.exists():
            try:
                m = re.search(r"^##\s*(?:Active Goal|Goal|Cel)\s*\n+(.+)$", state.read_text(encoding="utf-8", errors="replace"), re.M)
                return m.group(1).strip() if m else ""
            except Exception:
                return ""
        if (p / ".git").exists():
            return ""
        p = p.parent
    return ""


def parse_capsule(capsule: str) -> Dict[str, Any]:
    text = capsule or ""

    def grab(label: str) -> str:
        # 1. Bullet point: • Label: ... or - Label: ...
        m = re.search(rf"[•\*\-]\s*{label}:\s*(.+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # 2. Tag: <tag>...</tag>
        tag = label.lower().replace(" ", "_")
        m2 = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
        if m2:
            return m2.group(1).strip()
        # 3. Fact: <fact key="tag">...</fact>
        m3 = re.search(rf'<fact[^>]*key=[\"\']{tag}[\"\'][^>]*>(.*?)</fact>', text, re.IGNORECASE | re.DOTALL)
        if m3:
            return m3.group(1).strip()
        return ""

    scope = re.search(r'<ONA_CONTEXT[^>]*scope=\"([^\"]*)\"', text)
    if not scope:
        scope = re.search(r'<scope[^>]*name=\"([^\"]*)\"', text)

    raw_targets = grab("Target Files") or grab("targets")
    targets = [t.strip().strip("'\"") for t in raw_targets.strip("[]").split(",") if t.strip()]

    return {
        "goal": grab("Goal") or grab("goal"),
        "spec": grab("Enhanced Technical Spec") or grab("spec"),
        "criteria": grab("Acceptance Criteria") or grab("criteria"),
        "targets": targets,
        "scope": scope.group(1) if scope else "",
        "project_line": grab("Project goal") or grab("project_goal"),
    }


def _call_key(t: Dict[str, Any]) -> str:
    """Identity of a call = tool + all arguments (a patch with different old/new strings is not a duplicate)."""
    args = t.get("args") if "args" in t else t.get("tool_args", {})
    if not isinstance(args, dict):
        args = {"_raw": str(args)}
    name = str(t.get("name") or t.get("tool_name") or "")
    return name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)[:600]


# ---------------------------------------------------------------- alignment chain
def check_alignment(prompt: str, capsule: Optional[str], cap: Dict[str, Any], goal: str, tools: List[Dict[str, Any]],
                    scope_dirs: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    edited = []
    for t in tools:
        if t.get("name") in ("write_file", "patch", "file_write"):
            args = t.get("args") if "args" in t else t.get("tool_args", {})
            if isinstance(args, dict):
                p = str(args.get("path") or args.get("filepath") or args.get("filename") or "")
                if p:
                    edited.append(p)

    if capsule is not None:  # None = historical turn, capsule text not retained
        if not capsule.strip():
            out.append(finding("capsule_missing", "no ONA_CONTEXT capsule recorded for the turn"))
        else:
            if cap.get("goal") and overlap(prompt, cap["goal"]) < 0.3 and overlap(cap["goal"], prompt) < 0.5:
                out.append(finding("capsule_goal_stale", f"prompt='{prompt[:90]}' vs capsule goal='{cap['goal'][:90]}'"))
            elif cap.get("goal") and len(prompt) > 140 and len(cap["goal"]) < 0.6 * len(prompt):
                out.append(finding("capsule_goal_truncated", f"prompt {len(prompt)} chars, capsule goal {len(cap['goal'])} chars"))
            if edited and not (cap.get("spec") or cap.get("criteria")):
                out.append(finding("spec_missing", f"{len(edited)} edits, capsule has no spec/criteria"))
            if goal and not cap.get("project_line") and overlap(goal, capsule) < 0.4:
                out.append(finding("project_goal_absent", f"STATE.md goal '{goal[:80]}' not present in capsule"))
            if cap.get("targets") and edited and not any(any(t in e for e in edited) for t in cap["targets"]):
                out.append(finding("targets_untouched", f"targets={cap['targets'][:3]} edited={[e.split('/')[-1] for e in edited[:3]]}"))

    if goal and len(words(prompt)) >= 4 and overlap(goal, prompt) == 0 and overlap(prompt, goal) == 0:
        out.append(finding("project_goal_offtrack", f"goal '{goal[:70]}' vs prompt '{prompt[:70]}'"))
    if len(scope_dirs) > 1:
        out.append(finding("scope_split", f"session dirs under scopes: {', '.join(scope_dirs)}"))
    return out


# ---------------------------------------------------------------- output vs evidence
def check_output(prompt: str, output: str, tools: List[Dict[str, Any]], verify: set, code_ext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    names = [t.get("name") or t.get("tool_name", "") for t in tools]
    claim = re.search(r"\b(działa|gotowe|zrobione|wdrożone|naprawione|works|fixed|deployed|all tests pass)\b", output or "", re.I)
    if claim and not any(n in verify for n in names):
        out.append(finding("claim_without_proof", f"output claims '{claim.group(0)}' with tools={sorted(set(names))[:5]}"))

    last_verify = max((i for i, n in enumerate(names) if n in verify), default=-1)
    late_edits = []
    for i, t in enumerate(tools):
        if i > last_verify and t.get("name") in ("write_file", "patch", "file_write"):
            args = t.get("args") if "args" in t else t.get("tool_args", {})
            if isinstance(args, dict):
                p = str(args.get("path") or args.get("filepath") or args.get("filename") or "")
                if code_ext.search(p):
                    late_edits.append(p)

    if late_edits:
        out.append(finding("edit_not_verified", f"{len(late_edits)} code edits after last verification: {late_edits[-1].split('/')[-1]}"))
    if is_polish(prompt) and len(output or "") > 200 and not is_polish(output):
        out.append(finding("reply_language", f"Polish prompt, reply starts '{(output or '')[:60]}'"))
    return out


# ---------------------------------------------------------------- harness efficiency
def check_harness(tools: List[Dict[str, Any]], tele: Dict[str, Any], duration_s: Optional[float],
                  is_error_fn=None, trunc_markers=TRUNC_MARKERS) -> List[Dict[str, Any]]:
    if is_error_fn is None:
        is_error_fn = is_error
    out: List[Dict[str, Any]] = []
    n = len(tools)
    errs = [t for t in tools if t.get("error") or is_error_fn(str(t.get("result", "")))]
    if n >= 4 and len(errs) / n > 0.25:
        kinds = Counter(t.get("name", "") for t in errs).most_common(2)
        sample = re.sub(r"\s+", " ", str(errs[-1].get("result", "")))[:120]
        out.append(finding("tool_error_rate", f"{len(errs)}/{n} failed, top {kinds}; last: {sample}"))

    reads = Counter((str((t.get("args") or {}).get("path") or (t.get("args") or {}).get("filepath") or (t.get("args") or {}).get("filename") or ""),
                     (t.get("args") or {}).get("offset", 1))
                    for t in tools
                    if t.get("name") in ("read_file", "file_read") and ((t.get("args") or {}).get("path") or (t.get("args") or {}).get("filepath") or (t.get("args") or {}).get("filename")))
    hot = [(p, c) for p, c in reads.items() if c >= 3]
    if hot:
        (p, off), c = max(hot, key=lambda x: x[1])
        out.append(finding("reread_same_file", f"{p.split('/')[-1]} (offset {off}) read {c}x"))

    dup = [(k, c) for k, c in Counter(_call_key(t) for t in tools if t.get("name") not in ("vision_analyze", "vision_load", "read_file", "file_read")).items() if c > 1]
    if dup:
        k, c = max(dup, key=lambda x: x[1])
        out.append(finding("duplicate_calls", f"{len(dup)} repeated calls, worst {c}x: {k[:110]}"))

    truncated = [i for i, t in enumerate(tools) if any(m in str(t.get("result", "")) for m in trunc_markers)]
    refetch = sum(1 for i in truncated for j in range(i + 1, min(i + 4, n))
                  if _call_key(tools[j]) == _call_key(tools[i]) or
                  (tools[j].get("name") == tools[i].get("name") and tools[j].get("name") in ("read_file", "file_read", "terminal", "run_command", "code_execution_tool")))
    if truncated and refetch:
        out.append(finding("truncation_refetch", f"{len(truncated)} truncated results, {refetch} follow-up re-fetches"))

    stale = sum(1 for t in tools if "stale_write_blocked" in str(t.get("result", "")) or "Refusing to overwrite" in str(t.get("result", "")))
    if stale:
        out.append(finding("stale_write_blocked", f"{stale} write_file refusals"))

    if n > 40 or (duration_s or 0) > 1200:
        out.append(finding("long_turn", f"{n} tool calls, {round(duration_s or 0)} s"))

    if tele:
        if (tele.get("hook_total_ms") or 0) > 600:
            out.append(finding("hook_latency", f"hook_total_ms={tele['hook_total_ms']}"))
        if (tele.get("capsule_tokens_est") or 0) > 1800:
            out.append(finding("capsule_over_budget", f"capsule_tokens_est={tele['capsule_tokens_est']}"))
        if tele.get("degraded"):
            out.append(finding("telemetry_degraded", f"invariants_failed={str(tele.get('invariants_failed_json'))[:120]}"))

    return out


# ---------------------------------------------------------------- audit runner
def audit_turn(record: Dict[str, Any]) -> Dict[str, Any]:
    """Execute all audit rules on a standardized turn record."""
    prompt = str(record.get("prompt") or record.get("user_message") or "")
    output = str(record.get("output") or record.get("final_response") or "")
    tools = record.get("tools") if "tools" in record else record.get("tool_calls", [])
    if not isinstance(tools, list):
        tools = []

    capsule = record.get("capsule")
    capsule_goal_override = record.get("capsule_goal")
    duration_s = record.get("duration_s") or record.get("duration") or 0.0
    session_id = record.get("session_id") or record.get("context_id") or "default"
    turn_id = record.get("turn_id") or str(int(time.time() * 1000))
    cwd = record.get("cwd")
    scopes_val = record.get("scopes")
    scope_dirs = record.get("scope_dirs") or (list(scopes_val) if scopes_val is not None else ["general"])
    tele = record.get("telemetry") or record.get("tele") or {}

    cap = parse_capsule(capsule or "")
    if capsule_goal_override and not cap["goal"]:
        cap["goal"] = capsule_goal_override

    goal = project_goal(cwd) if cwd else (record.get("project_goal") or "")

    findings = (
        check_alignment(prompt, capsule, cap, goal, tools, scope_dirs)
        + check_output(prompt, output, tools, VERIFY_TOOLS, CODE_EXT)
        + check_harness(tools, tele, duration_s, is_error, TRUNC_MARKERS)
    )
    score = max(0, 100 - sum(SEVERITY_WEIGHT.get(f["severity"], 0) for f in findings))

    return {
        "ts": time.time(),
        "session": session_id,
        "context_id": session_id,
        "turn": turn_id,
        "score": score,
        "chain": {
            "project_goal": goal[:200],
            "prompt": prompt[:300],
            "capsule_goal": cap["goal"][:200],
            "spec": (cap["spec"] or cap["criteria"])[:200],
            "targets": cap["targets"][:5],
            "output": (output or "")[:300],
            "capsule_retained": capsule is not None,
        },
        "harness": {
            "tool_calls": len(tools),
            "errors": sum(1 for t in tools if t.get("error") or is_error(str(t.get("result", "")))),
            "tools": dict(Counter(t.get("name", "") for t in tools).most_common(8)),
            "duration_s": round(duration_s or 0, 1),
            "capsule_tokens": tele.get("capsule_tokens_est"),
            "hook_ms": tele.get("hook_total_ms"),
        },
        "findings": findings,
    }


def audit(session_id: str, turn_id: str, prompt: str, output: str, tools: List[Dict[str, Any]],
          capsule: Optional[str], tele: Dict[str, Any], scope_dirs: List[str], cwd: Optional[str],
          duration_s: Optional[float]) -> Dict[str, Any]:
    return audit_turn({
        "session_id": session_id,
        "turn_id": turn_id,
        "prompt": prompt,
        "output": output,
        "tools": tools,
        "capsule": capsule,
        "telemetry": tele,
        "scope_dirs": scope_dirs,
        "cwd": cwd,
        "duration_s": duration_s,
    })
