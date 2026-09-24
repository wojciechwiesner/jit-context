"""POST /api/plugins/jit_context/jit_status - live JIT/JEV telemetry + issue rules.

Read-only aggregation over data/jit_context.db and merged plugin config.
Never mutates state; safe to poll frequently. I6: on any failure returns
a degraded payload with issues instead of raising.
"""
from __future__ import annotations

import os
import sqlite3
import time

from helpers.api import ApiHandler, Request
from helpers import plugins


_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jit_context.db"
)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _ro():
    if not os.path.isfile(_DB):
        return None
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=2.0)


def _verdicts(conn):
    if conn is None:
        return {}
    rows = _safe(lambda: conn.execute(
        "SELECT verdict, COUNT(*) FROM shadow_verdicts GROUP BY verdict"
    ).fetchall(), [])
    return {v: c for v, c in rows}


def _telemetry(conn):
    if conn is None:
        return {}
    last = _safe(lambda: conn.execute(
        "SELECT duration_ms FROM telemetry_events "
        "WHERE stage='compile_capsule' ORDER BY id DESC LIMIT 1"
    ).fetchone(), None)
    tokens_avoided = _safe(lambda: conn.execute(
        "SELECT COALESCE(SUM(tokens_avoided),0) FROM telemetry_events"
    ).fetchone()[0], 0)
    compile_ms = round(float(last[0]), 2) if last else None
    return {"last_compile_ms": compile_ms, "tokens_avoided": int(tokens_avoided)}


def _counts(conn):
    empty = {"hot_facts": 0, "pruned_history": 0, "verdicts_total": 0}
    if conn is None:
        return empty
    hf = _safe(lambda: conn.execute("SELECT COUNT(*) FROM hot_facts").fetchone()[0], 0)
    ph = _safe(lambda: conn.execute("SELECT COUNT(*) FROM pruned_history").fetchone()[0], 0)
    vt = _safe(lambda: conn.execute("SELECT COUNT(*) FROM shadow_verdicts").fetchone()[0], 0)
    return {"hot_facts": int(hf), "pruned_history": int(ph), "verdicts_total": int(vt)}


def _has_columns(conn, table, wanted):
    cols = _safe(lambda: [c[1] for c in conn.execute(f"PRAGMA table_info({table})")], [])
    return all(w in cols for w in wanted)


def _cache_hit_tracked(conn):
    if conn is None:
        return False
    n = _safe(lambda: conn.execute(
        "SELECT COUNT(*) FROM telemetry_events WHERE cache_hit_rate IS NOT NULL"
    ).fetchone()[0], 0)
    return n > 0


def _rules(cfg, verdicts, counts, conn):
    """Issue rules from DESIGN.md section 4."""
    issues = []
    helpful = verdicts.get("HELPFUL", 0)
    db_age_h = None
    if os.path.isfile(_DB):
        db_age_h = round((time.time() - os.path.getmtime(_DB)) / 3600.0, 1)

    if cfg.get("mode") == "active" and helpful > 10 and counts["hot_facts"] == 0:
        issues.append({
            "level": "error", "code": "l2_no_promotion",
            "title": "L2 promotion idle",
            "detail": f"{helpful} HELPFUL verdicts but hot_facts=0; gate never promoted a fact.",
            "fix": "Check l2_mode threshold and promotion gate logs.",
        })
    if conn is not None and not _has_columns(conn, "shadow_verdicts", ["fact_key", "reason"]):
        issues.append({
            "level": "error", "code": "judge_no_content",
            "title": "Shadow judge stores no content",
            "detail": "shadow_verdicts lacks fact_key/reason columns; HARMFUL verdicts cannot be audited.",
            "fix": "Extend schema with fact_key, reason, confidence.",
        })
    if conn is not None and counts["verdicts_total"] > 0 and not _cache_hit_tracked(conn):
        issues.append({
            "level": "warn", "code": "cache_hit_untracked",
            "title": "Cache hit rate not measured",
            "detail": "cache_hit_rate is NULL across telemetry.",
            "fix": "Add hit/miss measurement in compile_capsule stage.",
        })
    if cfg.get("jev_remote_enabled") and not str(cfg.get("jev_http_url") or "").strip():
        issues.append({
            "level": "warn", "code": "jev_no_remote_fallback",
            "title": "JEV remote fallback empty",
            "detail": "jev_http_url is empty; if the local judge fails there is no fallback.",
            "fix": "Set jev_http_url or accept local-only mode.",
        })
    if cfg.get("mode") == "active" and db_age_h is not None and db_age_h > 24:
        issues.append({
            "level": "error", "code": "db_stale",
            "title": "Database stale >24h",
            "detail": f"jit_context.db last write {db_age_h}h ago while mode=active.",
            "fix": "Verify extensions fire (agent_init, message_loop_end).",
        })
    if counts["pruned_history"] == 0:
        issues.append({
            "level": "info", "code": "fence_no_prune",
            "title": "Fence never pruned",
            "detail": "pruned_history=0; sessions shorter than the fence window.",
            "fix": "No action needed; informational.",
        })
    return issues


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        cfg = plugins.get_plugin_config("jit_context") or {}
        conn = _safe(_ro, None)
        verdicts = _verdicts(conn)
        tel = _telemetry(conn)
        counts = _counts(conn)
        issues = _rules(cfg, verdicts, counts, conn)
        if conn is not None:
            conn.close()
        db_mtime = None
        if os.path.isfile(_DB):
            db_mtime = int(os.path.getmtime(_DB))
        l2_mode = "off" if not cfg.get("l2_enabled") else str(cfg.get("l2_mode", "shadow"))
        return {
            "ok": True,
            "jit": {
                "mode": cfg.get("mode", "active"),
                "max_capsule_tokens": int(cfg.get("max_capsule_tokens", 1500)),
                "recent_turn_fence": int(cfg.get("recent_turn_fence", 4)),
                "l2_mode": l2_mode,
                **tel,
                "db_mtime": db_mtime,
            },
            "jev": {
                "enabled": bool(cfg.get("jev_enabled", True)),
                "distill_enabled": bool(cfg.get("jev_distill_enabled", True)),
                "distill_max_facts": int(cfg.get("jev_distill_max_facts", 3)),
                "remote_enabled": bool(cfg.get("jev_remote_enabled", True)),
                "remote_url": str(cfg.get("jev_http_url") or ""),
                "verdicts": verdicts,
            },
            "tiers": {
                "l0": bool(cfg.get("l0_enabled", True)),
                "l1": bool(cfg.get("l1_enabled", True)),
                "l2": l2_mode,
            },
            "counts": counts,
            "issues": issues,
        }
