#!/usr/bin/env python3
"""Harness-side localization eval on SWE-bench Verified (no LLM).

For each instance, rank the repo's Python source files at base_commit against
the problem statement and report whether the gold-patch files land in top-k.
Reads files straight from bare git mirrors (no checkout), so it is cheap on disk.

Usage:
  python localize_eval.py --ids swe_50_ids.txt --out /tmp/localize_50.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import warnings
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from rank_bm25 import BM25Okapi

HERE = Path(__file__).resolve().parent
FULL_CACHE = Path.home() / ".hermes/cache/swe_repos"          # shared with agent.py
SHALLOW_CACHE = Path.home() / ".hermes/cache/swe_repos_shallow"
KS = (1, 3, 5, 10)
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PATH_RE = re.compile(r"[\w./-]+\.py\b")


def mirror_for(repo: str, commit: str) -> Path:
    """Full mirror if agent.py already cloned it, else a depth-1 fetch of just this commit.

    Blobless partial clones fetch missing blobs one by one (minutes per repo), so they
    are not used here; a shallow fetch pulls one full tree in a single pack.
    """
    name = repo.replace("/", "__")
    full = FULL_CACHE / name
    if full.exists():
        return full
    dest = SHALLOW_CACHE / name
    if not dest.exists():
        dest.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(dest)], check=True)
    has_commit = subprocess.run(["git", "-C", str(dest), "cat-file", "-e", f"{commit}^{{tree}}"],
                                capture_output=True).returncode == 0
    if not has_commit:
        subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1",
                        f"https://github.com/{repo}.git", commit], check=True)
    return dest


def git(mirror: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(mirror), *args], input=stdin,
                          capture_output=True, check=True).stdout


def source_files(mirror: Path, commit: str) -> dict[str, str]:
    """Non-test .py files at commit -> text. One batched blob read."""
    listing = git(mirror, "ls-tree", "-r", commit).decode().splitlines()
    entries = []
    for line in listing:
        meta, path = line.split("\t", 1)
        if not path.endswith(".py") or is_test_path(path):
            continue
        entries.append((meta.split()[2], path))
    if not entries:
        return {}
    # one batched blob read for all files
    oids = "\n".join(o for o, _ in entries).encode() + b"\n"
    raw = git(mirror, "cat-file", "--batch", stdin=oids)
    out, pos = {}, 0
    for oid, path in entries:
        nl = raw.index(b"\n", pos)
        size = int(raw[pos:nl].split()[2])
        out[path] = raw[nl + 1: nl + 1 + size].decode("utf-8", "replace")
        pos = nl + 1 + size + 1
    return out


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    return any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith("test_")


def split_ident(tok: str) -> list[str]:
    pieces = re.sub(r"([a-z])([A-Z])", r"\1 \2", tok).replace("_", " ").lower().split()
    return [tok.lower()] + [p for p in pieces if len(p) > 1]


def tokenize(text: str) -> list[str]:
    out = []
    for t in TOKEN_RE.findall(text):
        out.extend(split_ident(t))
    return out


def symbols(src: str) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # repo code, not ours
            tree = ast.parse(src)
    except SyntaxError:
        return ""
    return " ".join(n.name for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def gold_files(patch: str) -> list[str]:
    return sorted({m for m in re.findall(r"^diff --git a/(\S+)", patch, re.M)})


def rank(files: dict[str, str], query: str, mode: str) -> list[str]:
    paths = list(files)
    if mode == "content":
        docs = [tokenize(p) + tokenize(files[p]) for p in paths]
    elif mode == "symbols":
        docs = [tokenize(p) + tokenize(symbols(files[p])) for p in paths]
    else:
        raise ValueError(mode)
    scores = BM25Okapi(docs).get_scores(tokenize(query))
    order = sorted(range(len(paths)), key=lambda i: -scores[i])
    ranked = [paths[i] for i in order]
    return boost_mentions(ranked, query)


def boost_mentions(ranked: list[str], query: str) -> list[str]:
    """Paths or dotted modules literally mentioned in the issue go first."""
    mentioned = set()
    for m in PATH_RE.findall(query):
        mentioned.update(p for p in ranked if p.endswith(m.lstrip("./")))
    for mod in re.findall(r"\b[a-z_]+(?:\.[a-z_]+){2,}\b", query):
        stem = mod.replace(".", "/")
        mentioned.update(p for p in ranked if p.endswith(stem + ".py") or p.endswith(stem + "/__init__.py"))
    return [p for p in ranked if p in mentioned] + [p for p in ranked if p not in mentioned]


def hits(ranked: list[str], gold: list[str]) -> dict[str, dict[str, bool]]:
    return {f"@{k}": {"any": any(g in ranked[:k] for g in gold),
                      "all": all(g in ranked[:k] for g in gold)} for k in KS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=str(HERE / "swe_50_ids.txt"))
    ap.add_argument("--dataset", default=str(HERE / "verified.parquet"))
    ap.add_argument("--out", default="/tmp/localize_eval.json")
    args = ap.parse_args()

    ids = [i for i in Path(args.ids).read_text().replace("\n", ",").split(",") if i.strip()]
    rows = {r["instance_id"]: r for r in pq.read_table(args.dataset).to_pylist()}
    modes = ("content", "symbols")
    records, agg = [], {m: Counter() for m in modes}

    for n, iid in enumerate(ids, 1):
        r = rows[iid]
        files = source_files(mirror_for(r["repo"], r["base_commit"]), r["base_commit"])
        gold = gold_files(r["patch"])
        rec = {"instance_id": iid, "gold": gold, "n_files": len(files),
               "gold_in_index": all(g in files for g in gold)}
        for m in modes:
            ranked = rank(files, r["problem_statement"], m)
            h = hits(ranked, gold)
            rec[m] = {"top5": ranked[:5], "hits": h,
                      "gold_rank": [ranked.index(g) + 1 if g in ranked else None for g in gold]}
            for k, v in h.items():
                agg[m][k + "_any"] += v["any"]
                agg[m][k + "_all"] += v["all"]
        records.append(rec)
        print(f"[{n}/{len(ids)}] {iid} files={len(files)} gold_rank content={rec['content']['gold_rank']} "
              f"symbols={rec['symbols']['gold_rank']}", flush=True)

    summary = {m: {k: f"{v}/{len(ids)}" for k, v in sorted(agg[m].items())} for m in modes}
    Path(args.out).write_text(json.dumps({"n": len(ids), "summary": summary, "records": records}, indent=2))
    print(json.dumps(summary, indent=2))
    print("written", args.out)


if __name__ == "__main__":
    main()
