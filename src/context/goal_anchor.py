"""Goal Anchor: deterministic, verbatim-only goal extraction for the capsule.

Why not the whole message: the host (Hermes) already appends the capsule to the verbatim
user message, so "Goal: <entire message>" duplicated ~59% of capsule bytes.
Why not truncation: pasted digests put the actual ask at the END; head-cut keeps the paste.
Why not an LLM summary: a paraphrase is assistant-derived text (authority 0) sitting in the
authority-1.0 Goal slot (violates I1), costs latency and is not byte-stable.

Rules (every output byte is copied from the user message, original order preserved):
1. Messages <= limit are returned verbatim.
2. Quoted/pasted material (code fences, '>' quotes, blocks after '---', transcript lines like
   '- Name: text' / '[12:03] Name:') is excluded from scoring, so imperatives inside a pasted
   WhatsApp digest are not mistaken for the user's own ask.
3. Sentences are scored: imperative/request/question cues + position (tail > head, because
   users usually paste first and ask last). Negation/contrast sentences are kept together
   with the following sentence ("Don't refactor X. Just fix the test.").
4. Selected sentences are emitted in original order, joined by ' … ', then a marker states the
   anchor is an extract and the full message follows.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Tuple

DEFAULT_LIMIT = 300

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_TRANSCRIPT_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\[[^\]]{1,40}\]\s*)?[^\s:\[\]][^:\n]{0,39}:\s+\S",
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")

# Polish + English request cues (imperatives, modal requests, questions).
_CUE_RE = re.compile(
    r"\b(zrób|zrob|dodaj|popraw|napraw|sprawdź|sprawdz|zbadaj|pomyśl|pomysl|rozważ|rozwaz|"
    r"wybierz|zacommituj|zacomituj|wdróż|wdroz|uruchom|odpal|napisz|przygotuj|usuń|usun|"
    r"zmień|zmien|ustaw|pokaż|pokaz|podsumuj|streść|stresc|odpowiedz|przeanalizuj|porównaj|"
    r"porownaj|zaimplementuj|stwórz|stworz|wyślij|wyslij|daj|chcę|chce|potrzebuję|potrzebuje|"
    r"proszę|prosze|czy|jak|dlaczego|co|gdzie|kiedy|ile|który|ktory|"
    r"please|fix|add|make|check|investigate|implement|create|remove|update|run|deploy|"
    r"summarize|write|explain|compare|choose|should|can you|could you|how|why|what|where|which)\b",
    re.IGNORECASE,
)
_NEGATION_START_RE = re.compile(r"^\s*(nie|don't|do not|never|zamiast|instead|ale nie|not)\b", re.IGNORECASE)


@dataclass(frozen=True)
class GoalAnchor:
    text: str
    is_verbatim_full: bool
    source_chars: int
    source_hash: str

    def render(self) -> str:
        if self.is_verbatim_full:
            return self.text
        return (
            f"{self.text} [ANCHOR: verbatim extract, not a summary; full message "
            f"({self.source_chars} chars, #{self.source_hash}) is the user turn itself]"
        )


def _strip_pasted_blocks(text: str) -> Tuple[str, bool]:
    """Remove fenced code, '>' quotes and transcript-style lines ('[ts] Name: text').

    A 'Name: text' line only counts as pasted when it carries a [timestamp] or when the
    message has >= 3 such lines (a single 'Kontekst: ...' line is the user's own prose).
    """
    had_paste = False
    t = _FENCE_RE.sub(" ", text)
    if t != text:
        had_paste = True
    lines = t.splitlines()
    speaker_lines = sum(1 for l in lines if _TRANSCRIPT_LINE_RE.match(l))
    kept: List[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            had_paste = True
            continue
        if _TRANSCRIPT_LINE_RE.match(line) and (s.startswith("[") or speaker_lines >= 3):
            had_paste = True
            continue
        kept.append(line)
    return "\n".join(kept), had_paste


def _head_tail(msg: str, limit: int, sep: str) -> str:
    """Verbatim first line + as many trailing lines as fit (pure-paste messages)."""
    lines = [l.strip() for l in msg.splitlines() if l.strip()]
    head = lines[0][: limit // 3]
    budget = limit - len(head) - len(sep)
    tail: List[str] = []
    for line in reversed(lines[1:]):
        if len(line) + 1 > budget:
            break
        tail.insert(0, line)
        budget -= len(line) + 1
    if not tail and len(lines) > 1:
        tail = [lines[-1][-max(20, budget):]]
    out = f"{head}{sep}{' / '.join(tail)}" if tail else head
    return out[:limit]


def _sentences(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in _SENT_SPLIT_RE.split(text):
        s = _LIST_ITEM_RE.sub("", raw).strip()
        if len(s) >= 3 and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _score(sentence: str, idx: int, n: int) -> float:
    cues = len(_CUE_RE.findall(sentence))
    score = min(cues, 3) * 2.0
    if sentence.rstrip().endswith("?"):
        score += 2.0
    # Position prior: users paste first and ask last; the opening line is often the ask too.
    if n > 1:
        rel = idx / (n - 1)
        score += 1.5 * rel
        if idx == 0:
            score += 1.0
    # Very long sentences are usually pasted content, not the instruction.
    if len(sentence) > 400:
        score -= 2.0
    return score


def build_goal_anchor(message: str, limit: int = DEFAULT_LIMIT) -> GoalAnchor:
    msg = (message or "").strip()
    digest = hashlib.sha1(msg.encode("utf-8")).hexdigest()[:8]
    if len(msg) <= limit:
        return GoalAnchor(msg, True, len(msg), digest)

    sep = " … "
    body, had_paste = _strip_pasted_blocks(msg)
    sents = _sentences(body)
    # Pure paste (e.g. a transcript with a one-line header): nothing of the user's own prose
    # to score beyond the header, so anchor on header + most recent lines, verbatim.
    if had_paste and not any(_CUE_RE.search(s) for s in sents) and sum(len(s) for s in sents) < 80:
        return GoalAnchor(_head_tail(msg, limit, sep), False, len(msg), digest)
    sents = sents or _sentences(msg)
    if not sents:
        return GoalAnchor(msg[:limit].rstrip(), False, len(msg), digest)

    n = len(sents)
    ranked = sorted(range(n), key=lambda i: (-_score(sents[i], i, n), -i))
    chosen: List[int] = []
    budget = limit
    for i in ranked:
        group = [i]
        # Keep a negation/contrast sentence glued to the sentence that follows it.
        if _NEGATION_START_RE.match(sents[i]) and i + 1 < n:
            group.append(i + 1)
        if i > 0 and _NEGATION_START_RE.match(sents[i - 1]) and (i - 1) not in chosen:
            group.insert(0, i - 1)
        new = [g for g in group if g not in chosen]
        cost = sum(len(sents[g]) for g in new) + len(sep) * len(new)
        if cost <= budget:
            chosen.extend(new)
            budget -= cost
        elif not chosen:
            # Top sentence alone exceeds the limit: keep its head and tail verbatim.
            s = sents[i]
            half = (limit - len(sep)) // 2
            return GoalAnchor(f"{s[:half].rstrip()}{sep}{s[-half:].lstrip()}", False, len(msg), digest)
        if budget < 40:
            break

    text = sep.join(sents[i] for i in sorted(chosen))
    return GoalAnchor(text, False, len(msg), digest)
