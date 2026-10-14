"""Deterministic per-project skill selection: must-have / optional / knowhow.

No LLM and no randomness. Score = IDF-weighted token overlap between project
signals and skill name/tags/description (name > tags > description), plus boosts
from STACK_SKILL_HINTS. Ties break on name, so two runs give identical output.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from context.skill_index import SkillEntry, scan_skills, tokenize
from context.skill_signals import (
    GENERIC_STACK_TOKENS, STACK_SKILL_HINTS, TEXT_STOPWORDS, ProjectSignals, collect_signals, normalize_hint_term,
)

DEFAULT_KNOWHOW_ROOT = Path.home() / "Documents" / "Wojciech" / "knowhow"
# Business/customer document trees, not engineering knowhow.
KNOWHOW_EXCLUDED_DIRS = frozenset({"application-partner", "business"})
OVERRIDE_FILENAME = "skills.override.json"

# Workflow skills that apply to every coding project (used only if present in the index).
ALWAYS_MUST = (
    "verification-before-completion",
    "systematic-debugging",
    "changelog-discipline",
    "jit-project-context",
)

MAX_MUST = 8
MAX_OPTIONAL = 10
MAX_KNOWHOW = 5
MUST_MIN_SCORE = 10.0
OPTIONAL_MIN_SCORE = 5.0
KNOWHOW_MIN_SCORE = 4.5

FIELD_WEIGHT_NAME = 3.0
FIELD_WEIGHT_TAGS = 2.0
FIELD_WEIGHT_DESC = 0.5
STACK_SIGNAL_WEIGHT = 1.0
TEXT_SIGNAL_WEIGHT = 0.3
TEXT_SCORE_CAP = 4.0
HINT_NAME_BOOST = 3.0
HINT_TAG_BOOST = 1.5
TEXT_HINT_FACTOR = 0.5
SCORE_PRECISION = 3


@dataclass(frozen=True)
class Pick:
    name: str
    score: float
    reason: str
    path: str


@dataclass
class Selection:
    must: List[Pick] = field(default_factory=list)
    optional: List[Pick] = field(default_factory=list)
    knowhow: List[Pick] = field(default_factory=list)


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _stems(text: str) -> frozenset:
    return frozenset(_stem(tok) for tok in tokenize(text))


@dataclass(frozen=True)
class _Doc:
    """Pre-tokenized searchable fields of one skill or note."""
    key: str
    path: str
    name_tokens: frozenset
    tag_tokens: frozenset
    desc_tokens: frozenset

    def all_tokens(self) -> frozenset:
        return self.name_tokens | self.tag_tokens | self.desc_tokens


def _skill_doc(skill: SkillEntry) -> _Doc:
    return _Doc(skill.name, str(skill.path), _stems(skill.name),
                _stems(" ".join(skill.tags)), _stems(skill.description))


def _idf_table(docs: Sequence[_Doc]) -> Dict[str, float]:
    doc_freq: Dict[str, int] = {}
    for doc in docs:
        for token in doc.all_tokens():
            doc_freq[token] = doc_freq.get(token, 0) + 1
    total = len(docs)
    return {tok: math.log(1.0 + total / (1.0 + freq)) for tok, freq in doc_freq.items()}


def _signal_weights(signals: ProjectSignals) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for term in signals.stack_terms:
        for token in _stems(term):
            if token not in GENERIC_STACK_TOKENS:
                weights[token] = STACK_SIGNAL_WEIGHT
    for token in _stems(signals.name.replace("-", " ").replace("_", " ")):
        if token not in TEXT_STOPWORDS:
            weights[token] = STACK_SIGNAL_WEIGHT
    for token in signals.text_tokens:
        weights.setdefault(_stem(token), TEXT_SIGNAL_WEIGHT)
    return weights


def _hint_keywords(signals: ProjectSignals) -> Dict[str, float]:
    """Hint keyword -> strongest factor, from stack terms (1.0) and free text (0.5)."""
    keywords: Dict[str, float] = {}
    sources = [(normalize_hint_term(t), 1.0) for t in signals.stack_terms]
    sources += [(normalize_hint_term(t), TEXT_HINT_FACTOR) for t in signals.frequent_text_tokens]
    for term, factor in sources:
        for keyword in STACK_SKILL_HINTS.get(term, ()):
            keywords[keyword] = max(keywords.get(keyword, 0.0), factor)
    return keywords


def _score_doc(doc: _Doc, weights: Dict[str, float], idf: Dict[str, float],
               hints: Dict[str, float]) -> Tuple[float, List[str]]:
    stack_score, text_score, reasons = 0.0, 0.0, []
    for token, weight in sorted(weights.items()):
        if token in doc.name_tokens:
            field_weight, where = FIELD_WEIGHT_NAME, "name"
        elif token in doc.tag_tokens:
            field_weight, where = FIELD_WEIGHT_TAGS, "tag"
        elif token in doc.desc_tokens:
            field_weight, where = FIELD_WEIGHT_DESC, "desc"
        else:
            continue
        points = weight * idf.get(token, 0.0) * field_weight
        if weight >= STACK_SIGNAL_WEIGHT:
            stack_score += points
            reasons.append(f"{token}({where})")
        else:
            text_score += points
    stack_score += _hint_score(doc, hints, reasons)
    # Free text alone can reach "optional" but never "must".
    return round(stack_score + min(text_score, TEXT_SCORE_CAP), SCORE_PRECISION), reasons


def _hint_score(doc: _Doc, hints: Dict[str, float], reasons: List[str]) -> float:
    total = 0.0
    for keyword, factor in sorted(hints.items()):
        stem = _stem(keyword)
        if stem in doc.name_tokens:
            total += HINT_NAME_BOOST * factor
            reasons.append(f"hint:{keyword}")
        elif stem in doc.tag_tokens:
            total += HINT_TAG_BOOST * factor
            reasons.append(f"hint:{keyword}")
    return total


def _reason(reasons: List[str]) -> str:
    return "matches " + ", ".join(reasons[:4]) if reasons else "text overlap with project docs"


def _rank(docs: Sequence[_Doc], signals: ProjectSignals) -> List[Pick]:
    idf = _idf_table(docs)
    weights, hints = _signal_weights(signals), _hint_keywords(signals)
    picks = []
    for doc in docs:
        score, reasons = _score_doc(doc, weights, idf, hints)
        picks.append(Pick(doc.key, score, _reason(reasons), doc.path))
    return sorted(picks, key=lambda pick: (-pick.score, pick.name))


def _read_override(project: Path) -> Dict[str, List[str]]:
    path = project / ".planning" / OVERRIDE_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: [str(x) for x in raw.get(key, [])] for key in ("must_add", "must_remove", "optional_add")}


def apply_override(selection: Selection, override: Dict[str, List[str]],
                   by_name: Dict[str, SkillEntry]) -> Selection:
    """Apply manual overrides last: must_remove, then must_add, then optional_add."""
    removed = set(override.get("must_remove", []))
    must = [p for p in selection.must if p.name not in removed]
    optional = [p for p in selection.optional if p.name not in removed]
    for name in override.get("must_add", []):
        if name in by_name and name not in {p.name for p in must}:
            must.append(Pick(name, 0.0, "manual override", str(by_name[name].path)))
            optional = [p for p in optional if p.name != name]
    for name in override.get("optional_add", []):
        known = {p.name for p in must + optional}
        if name in by_name and name not in known:
            optional.append(Pick(name, 0.0, "manual override", str(by_name[name].path)))
    return Selection(must=must, optional=optional, knowhow=selection.knowhow)


def _split_tiers(ranked: List[Pick], present_always: List[str]) -> Tuple[List[Pick], List[Pick]]:
    by_name = {pick.name: pick for pick in ranked}
    must = [Pick(n, by_name[n].score, "always-on workflow skill", by_name[n].path) for n in present_always]
    for pick in ranked:
        if len(must) >= MAX_MUST:
            break
        if pick.score >= MUST_MIN_SCORE and pick.name not in present_always:
            must.append(pick)
    chosen = {pick.name for pick in must}
    rest = [p for p in ranked if p.name not in chosen and p.score >= OPTIONAL_MIN_SCORE]
    return must, rest[:MAX_OPTIONAL]


def _knowhow_docs(root: Path) -> List[_Doc]:
    docs = []
    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        if path.relative_to(root).parts[0] in KNOWHOW_EXCLUDED_DIRS:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:30]
        except OSError:
            continue
        heading = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
        rel = path.relative_to(root).with_suffix("").as_posix()
        name_tokens = _stems(rel.replace("_", " ").replace("-", " "))
        docs.append(_Doc(rel, str(path), name_tokens, _stems(heading), frozenset()))
    return docs


def select_skills(
    project: Path,
    stack: Dict[str, Any],
    skills_root: Optional[Path] = None,
    knowhow_root: Optional[Path] = None,
    dossier_file: Optional[Path] = None,
) -> Selection:
    """Pick must / optional skills and knowhow notes for one project."""
    skills = scan_skills(skills_root) if skills_root else scan_skills()
    by_name = {skill.name: skill for skill in skills}
    signals = collect_signals(project, stack, dossier_file)
    ranked = _rank([_skill_doc(skill) for skill in skills], signals)
    present_always = [name for name in ALWAYS_MUST if name in by_name]
    must, optional = _split_tiers(ranked, present_always)
    notes = _rank(_knowhow_docs(knowhow_root or DEFAULT_KNOWHOW_ROOT), signals)
    knowhow = [n for n in notes if n.score >= KNOWHOW_MIN_SCORE][:MAX_KNOWHOW]
    selection = Selection(must=must, optional=optional, knowhow=knowhow)
    return apply_override(selection, _read_override(project), by_name)
