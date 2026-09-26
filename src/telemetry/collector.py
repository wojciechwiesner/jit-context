"""Telemetry collector logic for Context OS."""

import time
import json
import uuid
import hashlib
import sqlite3
from typing import Dict, Any, Optional, List

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

def emit_feed_event(
    conn: sqlite3.Connection,
    event_type: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    ref_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload_json = json.dumps(payload or {})
    conn.execute(
        """
        INSERT INTO telemetry_feed (created_at, event_type, session_id, turn_id, ref_id, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (now, event_type, session_id, turn_id, ref_id, payload_json)
    )
    conn.commit()

def record_turn_telemetry(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: str,
    user_query: str,
    active_scope: str,
    retrieval_scopes: List[str],
    l0_ms: float,
    l1_ms: float,
    l2_ms: float,
    compile_ms: float,
    hook_total_ms: float,
    capsule: str,
    mode: str = "shadow"
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    query_chars = len(user_query)
    query_tokens = query_chars // 4
    query_hash = compute_hash(user_query)
    
    capsule_chars = len(capsule)
    capsule_tokens = capsule_chars // 4
    capsule_hash = compute_hash(capsule)
    
    # Counterfactual baseline: full active project + knowhow + canon ~ 32k tokens
    haystack_tokens = 32000
    haystack_chars = haystack_tokens * 4
    avoided_tokens = max(0, haystack_tokens - capsule_tokens)
    compression = round((1.0 - (capsule_tokens / haystack_tokens)) * 100, 1) if haystack_tokens else 0.0
    
    is_l2 = 1 if l2_ms > 400 else 0
    conn.execute(
        """
        INSERT INTO turn_telemetry (
            session_id, turn_id, created_at, mode,
            user_query_chars, user_query_tokens_est, user_query_hash,
            active_scope, retrieval_scopes_json,
            l0_ms, l1_ms, l2_ms, compile_ms, hook_total_ms,
            capsule_hash, capsule_chars, capsule_tokens_est,
            haystack_chars_est, haystack_tokens_est, jit_tokens_avoided_est, compression_ratio,
            l2_triggered
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, turn_id) DO UPDATE SET
            l0_ms = excluded.l0_ms,
            l1_ms = excluded.l1_ms,
            l2_ms = excluded.l2_ms,
            compile_ms = excluded.compile_ms,
            hook_total_ms = excluded.hook_total_ms,
            capsule_hash = excluded.capsule_hash,
            capsule_chars = excluded.capsule_chars,
            capsule_tokens_est = excluded.capsule_tokens_est,
            jit_tokens_avoided_est = excluded.jit_tokens_avoided_est,
            l2_triggered = excluded.l2_triggered
        """,
        (
            session_id, turn_id, now, mode,
            query_chars, query_tokens, query_hash,
            active_scope, json.dumps(retrieval_scopes),
            l0_ms, l1_ms, l2_ms, compile_ms, hook_total_ms,
            capsule_hash, capsule_chars, capsule_tokens,
            haystack_chars, haystack_tokens, avoided_tokens, compression,
            is_l2
        )
    )
    conn.commit()
    emit_feed_event(conn, "turn_telemetry_recorded", session_id, turn_id, None, {
        "active_scope": active_scope,
        "hook_total_ms": hook_total_ms,
        "capsule_tokens": capsule_tokens,
        "avoided_tokens": avoided_tokens
    })

def record_llm_start(
    conn: sqlite3.Connection,
    api_request_id: str,
    session_id: Optional[str],
    turn_id: Optional[str],
    provider: str,
    requested_model: str,
    message_count: int = 0,
    tool_count: int = 0,
    approx_input_tokens: int = 0,
    retry_count: int = 0
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        INSERT INTO llm_metrics (
            api_request_id, session_id, turn_id, retry_count,
            started_at, provider, requested_model,
            message_count, tool_count, approx_input_tokens, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started')
        ON CONFLICT(api_request_id, retry_count) DO NOTHING
        """,
        (
            api_request_id, session_id, turn_id, retry_count,
            now, provider, requested_model,
            message_count, tool_count, approx_input_tokens
        )
    )
    conn.commit()
    emit_feed_event(conn, "llm_request_started", session_id, turn_id, api_request_id, {
        "provider": provider,
        "model": requested_model,
        "approx_input_tokens": approx_input_tokens
    })

def record_llm_success(
    conn: sqlite3.Connection,
    api_request_id: str,
    duration_ms: float,
    response_model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float = 0.0,
    retry_count: int = 0
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_tokens = input_tokens + output_tokens
    conn.execute(
        """
        UPDATE llm_metrics
        SET status = 'success', ended_at = ?, duration_ms = ?,
            response_model = ?, input_tokens = ?, output_tokens = ?,
            total_tokens = ?, cache_read_tokens = ?, cache_write_tokens = ?,
            cost_usd = ?
        WHERE api_request_id = ? AND retry_count = ?
        """,
        (
            now, duration_ms, response_model, input_tokens, output_tokens,
            total_tokens, cache_read_tokens, cache_write_tokens, cost_usd,
            api_request_id, retry_count
        )
    )
    conn.commit()
    emit_feed_event(conn, "llm_request_success", None, None, api_request_id, {
        "duration_ms": duration_ms,
        "response_model": response_model,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cost_usd": cost_usd
    })

def record_llm_error(
    conn: sqlite3.Connection,
    api_request_id: str,
    error_reason: str,
    duration_ms: float = 0.0,
    http_status: Optional[int] = None,
    retry_count: int = 0
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        UPDATE llm_metrics
        SET status = 'error', ended_at = ?, duration_ms = ?,
            error_reason = ?, http_status = ?
        WHERE api_request_id = ? AND retry_count = ?
        """,
        (now, duration_ms, error_reason, http_status, api_request_id, retry_count)
    )
    conn.commit()
    emit_feed_event(conn, "llm_request_error", None, None, api_request_id, {
        "error_reason": error_reason,
        "http_status": http_status
    })

def record_context_query(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: str,
    layer: str,
    target: str,
    trigger: str,
    query_text: str,
    duration_ms: float,
    status: str = "hit",
    returned_chars: int = 0
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    query_id = f"cq_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO context_queries (
            query_id, session_id, turn_id, created_at,
            layer, target, trigger, query_text,
            duration_ms, status, returned_chars, returned_tokens_est
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            query_id, session_id, turn_id, now,
            layer, target, trigger, query_text,
            duration_ms, status, returned_chars, returned_chars // 4
        )
    )
    conn.commit()
    emit_feed_event(conn, "context_query_executed", session_id, turn_id, query_id, {
        "layer": layer,
        "target": target,
        "duration_ms": duration_ms,
        "status": status
    })


def record_llm_tool_calls(
    conn: sqlite3.Connection,
    api_request_id: str,
    tool_names: List[str],
    retry_count: int = 0,
) -> None:
    """Store the tool calls the model emitted in one API response (post_api_request)."""
    conn.execute(
        "UPDATE llm_metrics SET tool_calls = ?, tool_names_json = ? WHERE api_request_id = ? AND retry_count = ?",
        (len(tool_names), json.dumps(tool_names), api_request_id, retry_count),
    )
    conn.commit()


def record_tool_recommendation(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: str,
    recommended: List[str],
    detected_domains: List[str],
) -> None:
    """Store what the domain router recommended for this turn (pre_llm_call)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        INSERT INTO tool_routing (session_id, turn_id, created_at, detected_domains_json, recommended_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id, turn_id) DO UPDATE SET
            detected_domains_json = excluded.detected_domains_json,
            recommended_json = excluded.recommended_json
        """,
        (session_id, turn_id, now, json.dumps(detected_domains), json.dumps(recommended)),
    )
    conn.commit()


def record_tool_use(conn: sqlite3.Connection, session_id: str, turn_id: str, tool_name: str) -> None:
    """Append an actually executed tool to the turn's routing row (post_tool_call)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row = conn.execute(
        "SELECT used_json FROM tool_routing WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tool_routing (session_id, turn_id, created_at, recommended_json, used_json, used_calls) "
            "VALUES (?, ?, ?, NULL, ?, 1)",
            (session_id, turn_id, now, json.dumps([tool_name])),
        )
    else:
        used = json.loads(row[0] or "[]")
        if tool_name not in used:
            used.append(tool_name)
        conn.execute(
            "UPDATE tool_routing SET used_json = ?, used_calls = used_calls + 1 WHERE session_id = ? AND turn_id = ?",
            (json.dumps(used), session_id, turn_id),
        )
    conn.commit()


def tool_routing_report(conn: sqlite3.Connection, limit: int = 200) -> Dict[str, Any]:
    """Aggregate recommended-vs-used: precision (recommended that were used) and recall
    (used that were recommended), over turns that had both a recommendation and tool use."""
    rows = conn.execute(
        "SELECT recommended_json, used_json FROM tool_routing ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    turns = with_rec = hits = rec_total = used_total = 0
    for rec_json, used_json in rows:
        turns += 1
        # Router names carry a sub-action ("terminal:curl_wa"); Hermes tool names do not.
        rec = {r.split(":", 1)[0] for r in json.loads(rec_json)} if rec_json else set()
        used = {u.split(":", 1)[0] for u in json.loads(used_json or "[]")}
        if not rec or not used:
            continue
        with_rec += 1
        hits += len(rec & used)
        rec_total += len(rec)
        used_total += len(used)
    return {
        "turns": turns,
        "turns_with_recommendation_and_use": with_rec,
        "precision": round(hits / rec_total, 3) if rec_total else None,
        "recall": round(hits / used_total, 3) if used_total else None,
    }
