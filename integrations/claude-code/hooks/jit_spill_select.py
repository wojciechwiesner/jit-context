"""Relevance-based selection of tool-output chunks for the JIT spillover hook.

A large tool output is split into chunks (one per JSON list item, or blocks of
lines for plain text), each chunk is scored against the user's last prompt
(JEV decisions API, falling back to deterministic token overlap), and the best
chunks are kept verbatim within a character budget. Omitted chunks are listed
as one-line labels so the model knows what exists in the raw spill file.
"""
from __future__ import annotations

import json
import os
import re
import time

TEXT_CHUNK_CHARS = 800
JEV_MAX_CANDIDATES = 40
JEV_VALUE_CHARS = 600
JEV_TIMEOUT_S = float(os.environ.get("JIT_SPILL_JEV_TIMEOUT", "2.5"))
LABEL_CHARS = 90
MAX_OMITTED_LABELS = 25
LABEL_KEYS = ("subject", "title", "summary", "name", "snippet", "message", "path", "url", "id")
OVERLAP_WEIGHT = 0.5
QUERY_MIN_CHARS = 60
QUERY_MAX_PROMPTS = 3


def last_user_prompt(transcript_path: str) -> str:
    """Recent real user messages, newest first, until the query carries enough signal.

    Short replies ("tak dla obu") rank chunks almost randomly, so earlier prompts are
    appended until QUERY_MIN_CHARS or QUERY_MAX_PROMPTS is reached.
    """
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, TypeError):
        return ""
    prompts = []
    for prompt in _user_prompts(reversed(lines)):
        prompts.append(prompt)
        if len(" | ".join(prompts)) >= QUERY_MIN_CHARS or len(prompts) >= QUERY_MAX_PROMPTS:
            break
    return " | ".join(prompts)[:500]


def _user_prompts(lines):
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if row.get("type") != "user" or row.get("isMeta"):
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
            yield content.strip()


def split_chunks(text: str) -> tuple[str, list[str], list[str]]:
    """Return (envelope, chunks, labels). JSON lists split per item, text per line block."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, list) and data:
        return "", [_compact(i) for i in data], [_label(i) for i in data]
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list) and v]
        if list_keys:
            key = max(list_keys, key=lambda k: len(_compact(data[k])))
            items = data[key]
            envelope = _compact({k: v for k, v in data.items() if k != key})
            envelope = f"{envelope} (+ list '{key}' with {len(items)} items)"
            return envelope, [_compact(i) for i in items], [_label(i) for i in items]
    blocks = _text_blocks(text)
    return "", blocks, [b[:LABEL_CHARS].replace("\n", " ") for b in blocks]


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _label(item) -> str:
    # Human-readable keys anywhere in the item beat a shallow opaque id.
    found = next((f for key in LABEL_KEYS if (f := _find_key(item, key, depth=0))), "")
    return (found or _compact(item))[:LABEL_CHARS].replace("\n", " ")


def _find_key(node, key: str, depth: int) -> str:
    if depth > 4:
        return ""
    if isinstance(node, dict):
        if isinstance(node.get(key), str) and node[key].strip():
            return node[key]
        children = node.values()
    elif isinstance(node, list):
        children = node[:1]
    else:
        return ""
    for child in children:
        found = _find_key(child, key, depth + 1)
        if found:
            return found
    return ""


def _text_blocks(text: str) -> list[str]:
    blocks, current = [], ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > TEXT_CHUNK_CHARS:
            blocks.append(current)
            current = ""
        current += line
    if current:
        blocks.append(current)
    return blocks


def _load_jev_key() -> None:
    """Load only JEV_OPENROUTER_KEY from ~/.hermes/.env (never the whole file)."""
    if os.environ.get("JEV_OPENROUTER_KEY"):
        return
    try:
        with open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8") as fh:
            for raw in fh:
                m = re.match(r"^\s*(?:export\s+)?JEV_OPENROUTER_KEY\s*=\s*['\"]?([^'\"\n#]+)", raw)
                if m:
                    os.environ["JEV_OPENROUTER_KEY"] = m.group(1).strip()
                    return
    except OSError:
        pass


def score_chunks(query: str, chunks: list[str]) -> tuple[list[float], str]:
    """Scores per chunk and the method used ('jev' or 'overlap')."""
    from cognitive.jev_engine import JevDecisionScorer, token_overlap_score, tokenize

    _load_jev_key()
    q_tokens = tokenize(query)
    overlap = [token_overlap_score(c, q_tokens) for c in chunks]
    ranked = sorted(range(len(chunks)), key=lambda i: -overlap[i])[:JEV_MAX_CANDIDATES]
    scores = [o * OVERLAP_WEIGHT for o in overlap]
    scorer = JevDecisionScorer(timeout_s=JEV_TIMEOUT_S)
    if not query or not scorer.is_available():
        return scores, "overlap"
    candidates = [{"key": f"c{i}", "value": chunks[i][:JEV_VALUE_CHARS]} for i in ranked]
    try:
        jev = scorer.score_remote(query, candidates) or {}
    except Exception:
        jev = {}
    if not jev:
        return scores, "overlap"
    for i in ranked:
        if f"c{i}" in jev:
            scores[i] = float(jev[f"c{i}"])
    return scores, "jev"


def select(text: str, query: str, budget: int) -> tuple[str, dict]:
    """Keep the most relevant chunks verbatim (in original order) plus an index of the rest."""
    t0 = time.time()
    envelope, chunks, labels = split_chunks(text)
    scores, method = score_chunks(query, chunks)
    order = sorted(range(len(chunks)), key=lambda i: -scores[i])
    kept, used = set(), len(envelope)
    for i in order:
        if used + len(chunks[i]) > budget and kept:
            continue
        kept.add(i)
        used += len(chunks[i])
    body = [envelope] if envelope else []
    body += [chunks[i][:budget] for i in sorted(kept)]
    omitted = [i for i in range(len(chunks)) if i not in kept]
    header = (f"[JIT spillover: kept {len(kept)}/{len(chunks)} chunks ranked by {method}"
              f" for: {query[:80]!r}]")
    lines = [header, *body]
    if omitted:
        lines.append(f"[omitted {len(omitted)} chunks:]")
        lines += [f"- #{i} (score {scores[i]:.2f}) {labels[i]}" for i in omitted[:MAX_OMITTED_LABELS]]
        if len(omitted) > MAX_OMITTED_LABELS:
            lines.append(f"- ... and {len(omitted) - MAX_OMITTED_LABELS} more")
    info = {"method": method, "kept": len(kept), "total": len(chunks), "ms": (time.time() - t0) * 1000}
    return "\n".join(lines), info
