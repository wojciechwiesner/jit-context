"""Plain-text SEARCH/REPLACE edits for small models: parse, apply, verify.

Code never travels inside JSON, so there is no escaping to get wrong. Matching is
tolerant (exact -> trailing whitespace -> uniform indentation shift) and a failed
match returns the closest region of the file so the model can copy it exactly.
"""
from __future__ import annotations

import ast
import difflib
import re
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

BLOCK_RE = re.compile(
    r"(?P<path>[^\s`'\"*]+\.py)[`'\"*]*[ \t]*\n"      # path line
    r"(?:```[\w-]*[ \t]*\n)?"                          # optional opening fence
    r"<{5,9} ?SEARCH[ \t]*\n(?P<search>.*?)\n?"
    r"={5,9}[ \t]*\n(?P<replace>.*?)\n?"
    r">{5,9} ?REPLACE",
    re.S,
)
IGNORED_FLAKES = ("imported but unused", "unable to detect undefined names")
LINENO_RE = re.compile(r"^\d+: ?")
DEF_RE = re.compile(r"^(async\s+def|def|class)\s+(\w+)")


@dataclass
class Edit:
    path: str
    search: str
    replace: str


def _strip_line_numbers(block: str) -> str:
    """Drop 'NNN: ' prefixes copied from read_file output (only if every non-empty line has one)."""
    lines = block.split("\n")
    body = [ln for ln in lines if ln.strip()]
    if not body or not all(re.match(r"^\d+: ", ln) or re.fullmatch(r"\d+:", ln) for ln in body):
        return block
    return "\n".join(LINENO_RE.sub("", ln, count=1) for ln in lines)


def parse_edits(text: str) -> list[Edit]:
    return [Edit(m["path"], _strip_line_numbers(m["search"]), _strip_line_numbers(m["replace"]))
            for m in BLOCK_RE.finditer(text or "")]


def _line_aligned_hits(text: str, search: str) -> list[int]:
    """Offsets where `search` occurs starting at a line start and ending at a line end.

    A substring hit in the middle of a line (e.g. SEARCH with 3-space indent inside a
    4-space line) would splice the replacement at the wrong column, so it does not count.
    """
    hits, start = [], text.find(search)
    while start != -1:
        end = start + len(search)
        at_line_start = start == 0 or text[start - 1] == "\n"
        at_line_end = end == len(text) or text[end] == "\n" or search.endswith("\n")
        if at_line_start and at_line_end:
            hits.append(start)
        start = text.find(search, start + 1)
    return hits


def _windows(lines: list[str], size: int):
    for i in range(len(lines) - size + 1):
        yield i, lines[i:i + size]


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _reindent(block: list[str], old: str, new: str) -> list[str]:
    out = []
    for ln in block:
        if ln.strip() and ln.startswith(old):
            ln = new + ln[len(old):]
        elif ln.strip():
            ln = new + ln.lstrip()
        out.append(ln)
    return out


def apply_edit(text: str, edit: Edit) -> tuple[str | None, str]:
    """Return (new_text, how) on success or (None, error_message)."""
    if not edit.search.strip():
        return None, "SEARCH section is empty; copy the existing lines you want to change."
    aligned = _line_aligned_hits(text, edit.search)
    if len(aligned) == 1:
        i = aligned[0]
        return text[:i] + edit.replace + text[i + len(edit.search):], "exact"
    if len(aligned) > 1:
        return None, f"SEARCH matches {len(aligned)} places; include more surrounding lines."

    lines = text.split("\n")
    s_lines = edit.search.split("\n")
    r_lines = edit.replace.split("\n")
    n = len(s_lines)

    rs = [ln.rstrip() for ln in s_lines]
    hits = [i for i, w in _windows(lines, n) if [x.rstrip() for x in w] == rs]
    if len(hits) == 1:
        i = hits[0]
        return "\n".join(lines[:i] + r_lines + lines[i + n:]), "trailing-whitespace"

    st = [ln.strip() for ln in s_lines]
    hits = [i for i, w in _windows(lines, n) if [x.strip() for x in w] == st]
    if len(hits) == 1:
        i = hits[0]
        first = next(k for k, ln in enumerate(s_lines) if ln.strip())
        new_block = _reindent(r_lines, _indent(s_lines[first]), _indent(lines[i + first]))
        return "\n".join(lines[:i] + new_block + lines[i + n:]), "indent-shift"
    if len(hits) > 1:
        return None, f"SEARCH matches {len(hits)} places (ignoring indentation); include more lines."
    return None, "SEARCH not found in file." + closest_hint(lines, s_lines)


def closest_hint(lines: list[str], s_lines: list[str]) -> str:
    target = "\n".join(ln.strip() for ln in s_lines)
    best, best_i = 0.0, -1
    for i, w in _windows(lines, len(s_lines)):
        sm = difflib.SequenceMatcher(None, target, "\n".join(x.strip() for x in w))
        if sm.real_quick_ratio() > best and sm.ratio() > best:
            best, best_i = sm.ratio(), i
    named = named_def_line(lines, s_lines)
    close_ok = best_i >= 0 and best >= 0.8
    if close_ok and (named is None or best_i <= named < best_i + len(s_lines)):
        lo, hi = best_i, min(len(lines), best_i + len(s_lines))
        return f" Closest match (lines {lo + 1}-{hi}, similarity {best:.0%}), copy from here:\n" + "\n".join(lines[lo:hi])
    anchor = named if named is not None else anchor_line(lines, s_lines)
    if anchor is None and best_i >= 0 and best >= 0.5:
        anchor = best_i
    if anchor is None:
        return " None of your SEARCH lines exist in this file. Read the file with read_file and copy the lines exactly."
    lo, hi = max(0, anchor - 4), min(len(lines), anchor + 25)
    body = "\n".join(lines[lo:hi])
    return (f" Your SEARCH does not match the real code. The file around line {anchor + 1} actually reads "
            f"(lines {lo + 1}-{hi}, copy exact text from here, without line numbers):\n{body}")


def named_def_line(lines: list[str], s_lines: list[str]) -> int | None:
    """Line index of the def/class that SEARCH names, if that name is defined exactly once."""
    stripped = [ln.strip() for ln in lines]
    for ln in s_lines:
        m = DEF_RE.match(ln.strip())
        if m:
            owners = [i for i, s in enumerate(stripped) if (d := DEF_RE.match(s)) and d[2] == m[2]]
            if len(owners) == 1:
                return owners[0]
    return None


def anchor_line(lines: list[str], s_lines: list[str]) -> int | None:
    """Index of the most distinctive SEARCH line that occurs exactly once in the file."""
    stripped = [ln.strip() for ln in lines]
    for cand in sorted({ln.strip() for ln in s_lines if len(ln.strip()) >= 8}, key=len, reverse=True):
        if stripped.count(cand) == 1:
            return stripped.index(cand)
    return None


def syntax_error(src: str) -> str | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            ast.parse(src)
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    return None


def flakes(src: str) -> set[str]:
    from pyflakes import checker
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(src)
    msgs = {m.message % m.message_args for m in checker.Checker(tree).messages}
    return {m for m in msgs if not any(k in m for k in IGNORED_FLAKES)}


def new_flakes(before: str, after: str) -> list[str]:
    try:
        return sorted(flakes(after) - flakes(before))
    except Exception:  # pyflakes is advisory; never block an edit on it
        return []


def resolve_path(repo_dir: Path, rel: str, tracked: list[str]) -> tuple[Path | None, str]:
    """Map a model-supplied path to a real repo file/dir.

    Order: as given -> drop leading segments ('path/to/pkg/x.py') -> unique basename.
    Returns (path, "") or (None, error message with candidates).
    """
    root = repo_dir.resolve()
    cleaned = rel.strip().strip("`'\"").lstrip("/")
    cleaned = cleaned[2:] if cleaned.startswith("./") else cleaned
    if cleaned in ("", "."):
        return root, ""
    parts = cleaned.split("/")
    for i in range(len(parts)):
        cand = (root / "/".join(parts[i:])).resolve()
        if str(cand).startswith(str(root)) and cand.exists():
            return cand, ""
    name = parts[-1]
    same = [f for f in tracked if f.rsplit("/", 1)[-1] == name]
    if len(same) == 1:
        return root / same[0], ""
    close = same[:8] or difflib.get_close_matches(cleaned, tracked, n=5, cutoff=0.5)
    hint = ("Candidates: " + ", ".join(close)) if close else "Use find_file to locate it."
    return None, f"path '{rel}' does not exist in the repository. {hint}"


def diff_hunk(repo_dir: Path, rel: str, limit: int = 60) -> str:
    out = subprocess.run(["git", "-C", str(repo_dir), "diff", "-U2", "--", rel],
                         capture_output=True, text=True).stdout.splitlines()
    body = [ln for ln in out if not ln.startswith(("diff --git", "index ", "--- ", "+++ "))]
    more = f"\n... ({len(body) - limit} more diff lines)" if len(body) > limit else ""
    return "\n".join(body[:limit]) + more
