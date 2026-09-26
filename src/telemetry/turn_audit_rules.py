"""Check catalog for the per-turn autochecker (telemetry/turn_audit.py).

Each check is deterministic and cheap. A failed check becomes a *finding*; findings are merged by key into the
jitjevmods.md backlog, so the same problem seen on 30 turns is one mod with count=30, not 30 lines.
"""
from __future__ import annotations

import json
import re
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
                    "The same session writes overlay/meta under several scope dirs, so telemetry and RYOW facts fork. Pin the session dir to the first scope."),
    "targets_untouched": ("Spec target files were never touched", "JIT L2 prompt enhancer", "medium",
                          "Target Files in the capsule did not match what the agent actually edited. Ground targets in the AST working set."),
    "claim_without_proof": ("Success claimed without runtime proof", "Agent output / BIT-FALS gate", "high",
                            "Output says done/works but no terminal/browser/test call ran in the turn. Add a post-turn guard that demands evidence."),
    "edit_not_verified": ("Code edited after the last verification", "Agent workflow", "medium",
                          "Code files changed after the last terminal/test call. Run tests/lint after the final edit of the turn."),
    "tool_error_rate": ("High tool error rate", "Harness tool layer", "medium",
                        "More than 25% of tool calls failed. Inspect the dominant error class and fix the tool contract (see evidence)."),
    "duplicate_calls": ("Identical tool calls repeated", "Harness loop guard", "medium",
                        "The same tool+arguments ran more than once in a turn. Cache results in the L0 overlay or nudge via loop guard."),
    "reread_same_file": ("Same file read 3+ times in one turn", "JIT L1 AST working set", "medium",
                         "Keep the file's symbols/snippets in the working set so the agent does not re-read it."),
    "truncation_refetch": ("Tool output truncation forced re-fetches", "JIT tool-output micro-capping", "medium",
                           "Older tool results were cut by the context engine and the agent re-ran commands to see them. Spill full output to disk and cap by relevance, not age."),
    "stale_write_blocked": ("write_file refused as stale", "Hermes write guard", "low",
                            "The agent tried to overwrite a file it had not fully read. Prefer patch, or read the full file first."),
    "long_turn": ("Very long turn", "Agent planning", "low",
                  "Over 40 tool calls or 20 min in a single turn. Split into checkpoints with intermediate verification."),
    "hook_latency": ("JIT hook exceeded the 600 ms deadline", "JIT hot path", "medium",
                     "hook_total_ms is over the fail-open deadline. Profile L1/L2 and move work to the background."),
    "capsule_over_budget": ("Capsule above the elastic MVC ceiling", "JIT L2 elastic assembler", "low",
                            "Capsule exceeded ~1800 tokens. Check which section grew and tighten relevance filtering."),
    "telemetry_degraded": ("Turn telemetry marked degraded", "JIT telemetry", "medium",
                           "The turn ran in degraded mode (broker timeout or invariant failure). See invariants_failed_json."),
    "reply_language": ("Reply language differs from the prompt", "Agent output", "low",
                       "Prompt was Polish but the reply was mostly English (user rule: reply in Polish)."),
    # Benchmark-harness mods (recorded from run analysis, same ledger)
    "gaia_python_stateless": ("GAIA python_exec loses state between calls", "GAIA runner tool layer", "high",
                              "Each python_exec is a fresh `python -c`; the worker writes notebook-style code, so variables vanish (NameError). Keep one persistent interpreter per task."),
    "gaia_autoprint_breaks_code": ("GAIA auto-print wraps comments/brackets", "GAIA runner tool layer", "high",
                                   "tool_python_exec wraps the last line in print() even when it is a comment or a closing bracket, producing SyntaxError. Only wrap a last line that parses as an expression."),
    "gaia_missing_modules": ("GAIA sandbox missing scientific modules", "GAIA runner environment", "medium",
                             "Tasks import biopython (Bio) and similar packages that are not installed in the benchmark venv. Pre-install the GAIA module set."),
    "gaia_budget_forced_answers": ("GAIA answers forced by exhausted turn budget", "Loop guard / budget", "medium",
                                   "A large share of tasks hit the 15-turn cap and were forced to answer. Measure after the tool fixes; if still high, refund turns spent on tool-contract errors."),
}

STOP = set("a i w z na do to że się nie jak co czy po tak ten ta the and of to in is for on with that this it be are".split())
PL_WORDS = re.compile(r"\b(jest|nie|się|oraz|żeby|czy|jak|dla|teraz|zrób|zrob|sprawdz|sprawdź|działa|dzialal|gotowe|tak|też|tez)\b", re.I)
PL_CHARS = re.compile(r"[ąćęłńóśźż]", re.I)


def finding(key: str, evidence: str) -> Dict[str, Any]:
    title, component, severity, proposal = CATALOG[key]
    return {"key": key, "title": title, "component": component, "severity": severity, "proposal": proposal, "evidence": evidence}


SEVERITY_WEIGHT = {"high": 25, "medium": 10, "low": 4}


def words(text: str) -> set:
    return {w for w in re.findall(r"[a-ząćęłńóśźż0-9_]{3,}", (text or "").lower()) if w not in STOP}


def overlap(a: str, b: str) -> float:
    """Share of `a`'s content words present in `b` (asymmetric containment)."""
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa) if wa else 1.0


def is_polish(text: str) -> bool:
    return bool(PL_CHARS.search(text or "")) or len(PL_WORDS.findall(text or "")) >= 2


# ---------------------------------------------------------------- alignment chain
def check_alignment(prompt: str, capsule: Optional[str], cap: Dict[str, Any], goal: str, tools: List[Dict[str, Any]],
                    scope_dirs: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    edited = [str(t["args"].get("path", "")) for t in tools if t["name"] in ("write_file", "patch")]
    if capsule is not None:  # None = historical turn, capsule text not retained
        if not capsule.strip():
            out.append(finding("capsule_missing", "no ONA_CONTEXT capsule recorded for the turn"))
        else:
            if cap["goal"] and overlap(prompt, cap["goal"]) < 0.3 and overlap(cap["goal"], prompt) < 0.5:
                out.append(finding("capsule_goal_stale", f"prompt='{prompt[:90]}' vs capsule goal='{cap['goal'][:90]}'"))
            elif cap["goal"] and len(prompt) > 140 and len(cap["goal"]) < 0.6 * len(prompt):
                out.append(finding("capsule_goal_truncated", f"prompt {len(prompt)} chars, capsule goal {len(cap['goal'])} chars"))
            if edited and not (cap["spec"] or cap["criteria"]):
                out.append(finding("spec_missing", f"{len(edited)} edits, capsule has no spec/criteria"))
            if goal and not cap["project_line"] and overlap(goal, capsule) < 0.4:
                out.append(finding("project_goal_absent", f"STATE.md goal '{goal[:80]}' not present in capsule"))
            if cap["targets"] and edited and not any(any(t in e for e in edited) for t in cap["targets"]):
                out.append(finding("targets_untouched", f"targets={cap['targets'][:3]} edited={[e.split('/')[-1] for e in edited[:3]]}"))
    if goal and len(words(prompt)) >= 4 and overlap(goal, prompt) == 0 and overlap(prompt, goal) == 0:
        out.append(finding("project_goal_offtrack", f"goal '{goal[:70]}' vs prompt '{prompt[:70]}'"))
    if len(scope_dirs) > 1:
        out.append(finding("scope_split", f"session dirs under scopes: {', '.join(scope_dirs)}"))
    return out


# ---------------------------------------------------------------- output vs evidence
def check_output(prompt: str, output: str, tools: List[Dict[str, Any]], verify: set, code_ext) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    names = [t["name"] for t in tools]
    claim = re.search(r"\b(działa|gotowe|zrobione|wdrożone|naprawione|works|fixed|deployed|all tests pass)\b", output or "", re.I)
    if claim and not any(n in verify for n in names):
        out.append(finding("claim_without_proof", f"output claims '{claim.group(0)}' with tools={sorted(set(names))[:5]}"))
    last_verify = max((i for i, n in enumerate(names) if n in verify), default=-1)
    late_edits = [str(t["args"].get("path", "")) for i, t in enumerate(tools)
                  if i > last_verify and t["name"] in ("write_file", "patch") and code_ext.search(str(t["args"].get("path", "")))]
    if late_edits:
        out.append(finding("edit_not_verified", f"{len(late_edits)} code edits after last verification: {late_edits[-1].split('/')[-1]}"))
    if is_polish(prompt) and len(output or "") > 200 and not is_polish(output):
        out.append(finding("reply_language", f"Polish prompt, reply starts '{(output or '')[:60]}'"))
    return out


# ---------------------------------------------------------------- harness efficiency
def _call_key(t: Dict[str, Any]) -> str:
    """Identity of a call = tool + all arguments (a patch with different old/new strings is not a duplicate)."""
    return t["name"] + "|" + json.dumps(t["args"], sort_keys=True, ensure_ascii=False, default=str)[:600]


def check_harness(tools: List[Dict[str, Any]], tele: Dict[str, Any], duration_s: Optional[float], is_error, trunc_markers) -> List[Dict[str, Any]]:
    from collections import Counter
    out: List[Dict[str, Any]] = []
    n = len(tools)
    errs = [t for t in tools if is_error(t["result"])]
    if n >= 4 and len(errs) / n > 0.25:
        kinds = Counter(t["name"] for t in errs).most_common(2)
        sample = re.sub(r"\s+", " ", errs[-1]["result"])[:120]
        out.append(finding("tool_error_rate", f"{len(errs)}/{n} failed, top {kinds}; last: {sample}"))
    reads = Counter((str(t["args"].get("path")), t["args"].get("offset", 1)) for t in tools
                    if t["name"] == "read_file" and t["args"].get("path"))
    hot = [(p, c) for p, c in reads.items() if c >= 3]
    if hot:
        (p, off), c = max(hot, key=lambda x: x[1])
        out.append(finding("reread_same_file", f"{p.split('/')[-1]} (offset {off}) read {c}x"))
    dup = [(k, c) for k, c in Counter(_call_key(t) for t in tools if t["name"] not in ("vision_analyze", "read_file")).items() if c > 1]
    if dup:
        k, c = max(dup, key=lambda x: x[1])
        out.append(finding("duplicate_calls", f"{len(dup)} repeated calls, worst {c}x: {k[:110]}"))
    truncated = [i for i, t in enumerate(tools) if any(m in t["result"] for m in trunc_markers)]
    refetch = sum(1 for i in truncated for j in range(i + 1, min(i + 4, n)) if _call_key(tools[j]) == _call_key(tools[i]) or
                  (tools[j]["name"] == tools[i]["name"] and tools[j]["name"] in ("read_file", "terminal")))
    if truncated and refetch:
        out.append(finding("truncation_refetch", f"{len(truncated)} truncated results, {refetch} follow-up re-fetches"))
    stale = sum(1 for t in tools if "stale_write_blocked" in t["result"] or "Refusing to overwrite" in t["result"])
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
