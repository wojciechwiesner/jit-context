"""L2 Remote Broker Client with 600ms deadline, Circuit Breaker, and Fail-Open behavior."""

import time
import sqlite3
from typing import Optional, List
from l2.circuit_breaker import CircuitBreaker
from config import BORG_GATEWAY_URL, BORG_GATEWAY_KEY, L2_DEADLINE_MS

_CB = CircuitBreaker("borg_broker")
_HTTP_CLIENT = None


def _get_http_client():
    # Lazy: L2 is opt-in (JIT_L2_ENABLED), so a missing httpx must not break
    # the SessionStart/UserPromptSubmit hook for everyone who never enables it.
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        import httpx
        _HTTP_CLIENT = httpx.Client(
            base_url=BORG_GATEWAY_URL,
            timeout=L2_DEADLINE_MS / 1000.0,
            headers={"Authorization": f"Bearer {BORG_GATEWAY_KEY}"} if BORG_GATEWAY_KEY else {}
        )
    return _HTTP_CLIENT


def query_deep_context(
    query: str,
    scopes: List[str],
    conn: sqlite3.Connection
) -> Optional[str]:
    """Queries Borg/Honcho/Obsidian with strict 600ms deadline and fail-open.

    Invariant I6: If circuit breaker is OPEN, or remote broker times out/fails,
    it returns None immediately without throwing any exception to Hermes.
    """
    if not _CB.can_attempt(conn):
        # Circuit Breaker OPEN -> zero network overhead, fail-open
        return None

    start_time = time.perf_counter()
    try:
        resp = _get_http_client().post(
            "/api/v1/context/search",
            json={"query": query, "scopes": scopes, "limit": 3}
        )
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        
        if resp.status_code == 200:
            data = resp.json()
            _CB.record_success(conn, latency_ms)
            return data.get("summary") or data.get("content")
        else:
            _CB.record_failure(conn)
            return None
    except Exception:
        # Timeout, connection error, or missing httpx dependency -> record failure and fail-open
        _CB.record_failure(conn)
        return None
