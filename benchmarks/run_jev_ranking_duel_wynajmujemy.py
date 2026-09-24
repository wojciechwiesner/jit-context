#!/usr/bin/env python3
"""Ranking duel: heuristic token-overlap vs live JEV.

Corpus is the real Wynajmujemy.xyz backend. Each task has one real symbol,
other real symbols as distractors, and short lexical decoys that steal overlap.

Both rankers see the same text, up to 1200 characters of the real symbol.
The client no longer slices the fact or the query. This is not an agent loop
and not SWE-bench. The model has no tools.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cognitive.jev_engine import DECISIONS_URL, DEFAULT_MODEL, JevDecisionScorer, tokenize, token_overlap_score

REPO = Path("/Users/wojciechwiesner/Projects/active/arena_qwen_wynajmujemy")
OUT = ROOT / "benchmarks" / "results" / "jev_ranking_duel_wynajmujemy.json"
PREVIEW = 1200
PRODUCTION_TIMEOUT_MS = 10000
DECOY_COUNT = 12
DISTRACTORS = 8

# line is the def/class line already verified in the repo.
TASKS = [
    {
        "id": "ssrf-import",
        "query": "Block SSRF when importing a listing URL. Reject localhost, private networks, and cloud metadata.",
        "file": "compliance.py",
        "symbol": "validate_import_url",
        "line": 93,
        "must": ["ssrf", "loopback"],
    },
    {
        "id": "outbound-pke",
        "query": "Block outbound marketing when the phone came from a public listing. Prior consent is required.",
        "file": "compliance.py",
        "symbol": "evaluate_outbound",
        "line": 258,
        "must": ["marketing", "consent"],
    },
    {
        "id": "human-review",
        "query": "Mandatory human review before publication when the listing has a high-risk industry profile.",
        "file": "compliance.py",
        "symbol": "check_listing_review_requirement",
        "line": 389,
        "must": ["review", "high-risk"],
    },
    {
        "id": "stale-30",
        "query": "Declared availability is stale when the host has not confirmed it for 30 days.",
        "file": "models.py",
        "symbol": "is_stale",
        "line": 152,
        "must": ["stale", "30"],
    },
    {
        "id": "pause-stale",
        "query": "Pause active listings that stayed unconfirmed for more than 30 days.",
        "file": "server.py",
        "symbol": "pause_stale_listings",
        "line": 571,
        "must": ["paused_stale", "30"],
    },
    {
        "id": "confirm-availability",
        "query": "Host confirms availability and a paused_stale listing becomes active again.",
        "file": "server.py",
        "symbol": "confirm_listing_availability",
        "line": 539,
        "must": ["confirms", "paused_stale"],
    },
    {
        "id": "public-catalog",
        "query": "Public catalog search returns only active listings and hides drafts and pending review.",
        "file": "server.py",
        "symbol": "get_public_catalog",
        "line": 495,
        "must": ["active", "drafts"],
    },
    {
        "id": "approve-hash",
        "query": "Approve publication only if draft_hash still matches. A mismatch returns 409 conflict.",
        "file": "server.py",
        "symbol": "approve_listing_publication",
        "line": 405,
        "must": ["draft_hash", "pending_review"],
    },
    {
        "id": "resource-type",
        "query": "Resource type is the room: office, workstation, or training room. Not the profession.",
        "file": "models.py",
        "symbol": "ResourceType",
        "line": 20,
        "must": ["office_room", "workstation"],
    },
    {
        "id": "industry-profile",
        "query": "Industry profile is the profession using the room and stays distinct from resource type.",
        "file": "models.py",
        "symbol": "IndustryProfile",
        "line": 31,
        "must": ["industry", "resource"],
    },
    {
        "id": "draft-hash",
        "query": "Deterministic SHA-256 hash of the canonical listing draft before the host approves it.",
        "file": "models.py",
        "symbol": "compute_draft_hash",
        "line": 301,
        "must": ["sha-256", "canonical"],
    },
    {
        "id": "register-host",
        "query": "Register a host account and return a session token before creating a listing draft.",
        "file": "server.py",
        "symbol": "register_host",
        "line": 205,
        "must": ["host", "token"],
    },
    {
        "id": "source-permission",
        "query": "Decide if an offer source may be imported. OLX stays disabled unless the owner attests rights.",
        "file": "compliance.py",
        "symbol": "evaluate_source",
        "line": 160,
        "must": ["olx", "rights_attestation"],
    },
    {
        "id": "header-actions",
        "query": "Header button lets a host list a space.",
        "file": "web_ui.py",
        "symbol": "header_list_space",
        "line": 699,
        "span": 1,
        "must": ["list space"],
    },
    {
        "id": "header-find",
        "query": "Header button lets a visitor find spaces in the catalog.",
        "file": "web_ui.py",
        "symbol": "header_find_spaces",
        "line": 700,
        "span": 1,
        "must": ["find spaces"],
    },
]


def snippet(task: dict) -> str:
    lines = (REPO / task["file"]).read_text().splitlines()
    start = task["line"] - 1
    span = task.get("span", 40)
    raw = " ".join(line.strip() for line in lines[start : start + span] if line.strip())
    return raw[:PREVIEW]


def symbol_key(task: dict) -> str:
    return f"{task['file']}::{task['symbol']}"


def load_symbols() -> list[dict]:
    rows = []
    errors = []
    for task in TASKS:
        text = snippet(task)
        missing = [tok for tok in task["must"] if tok not in text.lower()]
        if missing:
            errors.append(f"{task['id']} missing {missing}: {text!r}")
        rows.append({"key": symbol_key(task), "value": text, "kind": "real"})
    if errors:
        raise SystemExit("\n".join(errors))
    return rows


def decoys_for(query: str) -> list[dict]:
    tokens = sorted(tokenize(query))
    if len(tokens) < 3:
        raise SystemExit(f"query too thin to build a lexical trap: {query}")
    rows = []
    for i in range(DECOY_COUNT):
        # Short body made only of query tokens, so overlap / length is 1.0.
        body_tokens = tokens[i % len(tokens) : i % len(tokens) + 3]
        if len(body_tokens) < 3:
            body_tokens = tokens[:3]
        key = f"a{i:02d}_{body_tokens[0]}.py"
        rows.append({"key": key, "value": " ".join(body_tokens), "kind": "decoy"})
    return rows


def heuristic_rank(query: str, candidates: list[dict]) -> list[tuple[str, float, str]]:
    q_tokens = tokenize(query)
    scored = []
    for item in candidates:
        text = f"{item['key']} {item['value'][:PREVIEW]}"
        scored.append((item["key"], token_overlap_score(text, q_tokens), item["kind"]))
    scored.sort(key=lambda row: (-row[1], row[0]))
    return scored


def mrr(ranked_keys: list[str], target: str) -> float:
    try:
        return 1.0 / (ranked_keys.index(target) + 1)
    except ValueError:
        return 0.0


def score_live(query: str, candidates: list[dict], api_key: str) -> dict:
    """Same decisions payload as the client, without the 200-character slice."""
    t0 = time.time()
    questions = {}
    for i, item in enumerate(candidates):
        val = item["value"][:PREVIEW]
        questions[f"q_{i}"] = {
            "type": "noul",
            "instructions": f"Fact [{item['key']}: {val}] is relevant for: {query}",
        }
    payload = {
        "model": DEFAULT_MODEL,
        "state": {"query": query, "task": "evaluate candidate relevance"},
        "questions": questions,
    }
    req = urllib.request.Request(
        DECISIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-jit-context-os/0.2.0 (JevRankingDuel)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            status_code = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "scores": {},
            "latency_ms": round((time.time() - t0) * 1000, 2),
            "http_status": exc.code,
            "remote_call_success": False,
            "fallback_used": True,
            "model": DEFAULT_MODEL,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except Exception as exc:
        return {
            "scores": {},
            "latency_ms": round((time.time() - t0) * 1000, 2),
            "http_status": None,
            "remote_call_success": False,
            "fallback_used": True,
            "model": DEFAULT_MODEL,
            "error": str(exc),
        }
    scores = {}
    for i, item in enumerate(candidates):
        ans = data.get("answers", {}).get(f"q_{i}", {})
        p = 0.0
        if isinstance(ans, dict):
            p = float(ans.get("noul", ans.get("probability", ans.get("p", ans.get("score", 0.0)))))
        elif isinstance(ans, (int, float)):
            p = float(ans)
        scores[item["key"]] = p
    return {
        "scores": scores,
        "latency_ms": round((time.time() - t0) * 1000, 2),
        "http_status": status_code,
        "remote_call_success": status_code == 200,
        "fallback_used": False,
        "model": data.get("model") or DEFAULT_MODEL,
        "error": None,
    }


def main() -> None:
    symbols = load_symbols()
    by_key = {row["key"]: row for row in symbols}
    scorer = JevDecisionScorer(timeout_s=45.0)
    if not scorer.api_key:
        raise SystemExit("JEV_OPENROUTER_KEY missing")

    details = []
    for task in TASKS:
        target = symbol_key(task)
        others = [row for row in symbols if row["key"] != target]
        # Stable distractors: skip a rotating window so the same 8 are not always present.
        shift = TASKS.index(task) % len(others)
        rotated = others[shift:] + others[:shift]
        pool = [by_key[target], *rotated[:DISTRACTORS], *decoys_for(task["query"])]
        if len(pool) > 40:
            raise SystemExit(f"{task['id']} exceeds JEV max_facts")

        h_ranked = heuristic_rank(task["query"], pool)
        h_keys = [key for key, _, _ in h_ranked]
        candidates = [{"key": item["key"], "value": item["value"][:PREVIEW]} for item in pool]
        detail = scorer.score_remote_detailed(task["query"], candidates)
        scores = detail.get("scores") or {}
        j_ranked = sorted(candidates, key=lambda item: (-float(scores.get(item["key"], 0.0)), item["key"]))
        j_keys = [item["key"] for item in j_ranked]
        top_h = h_keys[0]
        top_j = j_keys[0] if j_keys else None
        row = {
            "id": task["id"],
            "query": task["query"],
            "target": target,
            "n_candidates": len(pool),
            "n_decoys": DECOY_COUNT,
            "heuristic_top": top_h,
            "heuristic_top_kind": next(item["kind"] for item in pool if item["key"] == top_h),
            "heuristic_hit": top_h == target,
            "heuristic_rank": h_keys.index(target) + 1,
            "heuristic_score_target": next(score for key, score, _ in h_ranked if key == target),
            "heuristic_score_top": h_ranked[0][1],
            "jev_top": top_j,
            "jev_top_kind": next((item["kind"] for item in pool if item["key"] == top_j), None),
            "jev_hit": top_j == target,
            "jev_rank": (j_keys.index(target) + 1) if target in j_keys else None,
            "jev_score_target": scores.get(target),
            "jev_score_top": scores.get(top_j) if top_j else None,
            "latency_ms": detail.get("latency_ms"),
            "exceeds_production_timeout": (detail.get("latency_ms") or 0) > PRODUCTION_TIMEOUT_MS,
            "http_status": detail.get("http_status"),
            "remote_call_success": detail.get("remote_call_success"),
            "fallback_used": detail.get("fallback_used"),
            "model": detail.get("model"),
            "error": detail.get("error"),
        }
        details.append(row)
        print(
            f"{task['id']:22} H={'HIT' if row['heuristic_hit'] else 'MISS':4} "
            f"J={'HIT' if row['jev_hit'] else 'MISS':4} "
            f"lat={row['latency_ms']} status={row['http_status']} "
            f"j_top={row['jev_top_kind']}:{top_j}"
        )
        time.sleep(0.2)

    def rate(flag: str) -> float:
        return round(sum(1 for row in details if row[flag]) / len(details), 3)

    summary = {
        "n": len(details),
        "heuristic_top1": rate("heuristic_hit"),
        "jev_top1": rate("jev_hit"),
        "heuristic_mrr": round(sum(1.0 / row["heuristic_rank"] for row in details) / len(details), 3),
        "jev_mrr": round(
            sum((1.0 / row["jev_rank"]) if row["jev_rank"] else 0.0 for row in details) / len(details),
            3,
        ),
        "jev_picked_decoy": sum(1 for row in details if row["jev_top_kind"] == "decoy"),
        "jev_picked_wrong_real": sum(
            1 for row in details if row["jev_top_kind"] == "real" and not row["jev_hit"]
        ),
        "live_calls": sum(1 for row in details if row["remote_call_success"] and not row["fallback_used"]),
        "errors": sum(1 for row in details if row["error"]),
        "mean_latency_ms": round(
            sum(row["latency_ms"] or 0 for row in details) / len(details),
            1,
        ),
        "calls_over_3s": sum(1 for row in details if row["exceeds_production_timeout"]),
        "model": next((row["model"] for row in details if row["model"]), None),
    }
    payload = {
        "label": "wynajmujemy symbol ranking duel",
        "not": "not an agent loop, not SWE-bench, not the current file-header harness",
        "corpus": str(REPO),
        "preview_chars": PREVIEW,
        "summary": summary,
        "details": details,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print("SUMMARY", json.dumps(summary))
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
