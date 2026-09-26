"""Loop Guard: deterministic in-loop controller for agent tool loops.

Detects three failure modes observed in GAIA runs (14/17 failures ended with an
empty answer after exhausting the turn budget):

1. Exact repeat   - the same tool called with the same (normalized) arguments.
2. Near repeat    - web_search queries with high token overlap to a previous query.
3. No progress    - tool outputs that add almost no new tokens to the evidence pool.

The guard never answers on behalf of the model. It only emits a verdict the
worker loop turns into a steering message or a forced final-answer turn.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

_TOKEN_RE = re.compile(r"[a-z0-9]+")

CONTINUE = "continue"
NUDGE = "nudge"
FORCE_ANSWER = "force_answer"


def _tokens(text: str) -> Set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _call_signature(tool: str, args: Dict[str, Any]) -> str:
    try:
        norm = json.dumps(args, sort_keys=True, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        norm = str(args).lower()
    norm = re.sub(r"\s+", " ", norm)
    return hashlib.sha1(f"{tool}:{norm}".encode("utf-8")).hexdigest()


@dataclass
class GuardVerdict:
    action: str
    reason: str = ""
    message: str = ""


@dataclass
class LoopGuard:
    """Tracks tool-loop progress and decides when to steer or force an answer.

    max_turns: total turn budget of the worker loop.
    answer_reserve: turns reserved at the end for a forced, tool-less answer.
    stall_window: consecutive no-progress tool calls that count as a stall.
    max_nudges: stalls tolerated before forcing an answer early.
    """

    max_turns: int = 15
    answer_reserve: int = 1
    stall_window: int = 3
    max_nudges: int = 2
    novelty_threshold: float = 0.10
    near_repeat_threshold: float = 0.75

    _signatures: Set[str] = field(default_factory=set)
    _queries: List[Set[str]] = field(default_factory=list)
    _evidence: Set[str] = field(default_factory=set)
    _no_progress_streak: int = 0
    nudges: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)

    def last_tool_turn(self) -> int:
        """Last turn on which tools are still offered to the model."""
        return max(1, self.max_turns - self.answer_reserve)

    def classify_call(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Return a repeat label before executing a call, or None if the call is new."""
        sig = _call_signature(tool, args)
        if sig in self._signatures:
            return "exact_repeat"
        self._signatures.add(sig)
        if tool == "web_search":
            q = _tokens(str(args.get("query", "")))
            for prev in self._queries:
                if _jaccard(q, prev) >= self.near_repeat_threshold:
                    self._queries.append(q)
                    return "near_repeat"
            self._queries.append(q)
        return None

    def observe_output(self, turn: int, tool: str, output: str, repeat: Optional[str] = None) -> float:
        """Record a tool output and return its novelty ratio (new tokens / output tokens)."""
        toks = _tokens(output or "")
        new = toks - self._evidence
        novelty = (len(new) / len(toks)) if toks else 0.0
        self._evidence |= toks
        progressed = repeat is None and novelty >= self.novelty_threshold
        self._no_progress_streak = 0 if progressed else self._no_progress_streak + 1
        self.events.append({
            "turn": turn,
            "tool": tool,
            "repeat": repeat,
            "novelty": round(novelty, 3),
            "streak": self._no_progress_streak,
        })
        return novelty

    def after_turn(self, turn: int) -> GuardVerdict:
        """Decide what the worker loop should do before the next model call."""
        if turn >= self.last_tool_turn():
            return GuardVerdict(
                FORCE_ANSWER,
                "budget_exhausted",
                "TOOL BUDGET EXHAUSTED. Tools are now disabled. Using only the evidence "
                "gathered above, give your best final answer. If uncertain, still commit "
                "to the most likely value. End with: FINAL ANSWER: <value>",
            )
        if self._no_progress_streak >= self.stall_window:
            self._no_progress_streak = 0
            self.nudges += 1
            if self.nudges > self.max_nudges:
                return GuardVerdict(
                    FORCE_ANSWER,
                    "repeated_stall",
                    "LOOP DETECTED AGAIN: recent tool calls add no new evidence. Tools are "
                    "now disabled. Give your best final answer from the evidence above. "
                    "End with: FINAL ANSWER: <value>",
                )
            remaining = self.last_tool_turn() - turn
            return GuardVerdict(
                NUDGE,
                "stall",
                f"LOOP DETECTED: your last {self.stall_window} tool calls returned no new "
                f"information (repeated or near-identical calls). Change strategy: open a "
                f"specific source URL with web_extract, reformulate the search with different "
                f"entities, or compute from evidence you already have. {remaining} tool turns "
                f"left. If the evidence above already answers the task, answer now with "
                f"FINAL ANSWER: <value>.",
            )
        remaining = self.last_tool_turn() - turn
        if remaining == 2:
            return GuardVerdict(
                NUDGE,
                "budget_warning",
                "BUDGET: 2 tool turns left before tools are disabled. Prioritize the single "
                "most decisive check, then answer with FINAL ANSWER: <value>.",
            )
        return GuardVerdict(CONTINUE)

    def summary(self) -> Dict[str, Any]:
        return {
            "nudges": self.nudges,
            "repeats": sum(1 for e in self.events if e["repeat"]),
            "events": self.events,
        }
