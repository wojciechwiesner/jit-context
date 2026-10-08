"""SessionOverlay & WAL append logic implementing Invariants I1, I2, I7."""

import os
import time
import uuid
import sqlite3
from contextlib import closing
from typing import Optional, List, Dict, Tuple
from l0.recent_fence import compute_content_hash
from l0.epistemics import get_authority_for_role

def ensure_session(
    conn: sqlite3.Connection,
    session_id: str,
    default_scope: str = "general"
) -> Dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        cursor = conn.execute(
            "SELECT session_id, active_scope, scope_epoch, scope_confidence, last_seq, last_cwd FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if row:
            if isinstance(row, sqlite3.Row):
                return dict(row)
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))
    except Exception:
        cursor = conn.execute(
            "SELECT session_id, active_scope, scope_epoch, scope_confidence, last_seq FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        
    conn.execute(
        """
        INSERT INTO sessions (session_id, active_scope, scope_epoch, scope_confidence, last_seq, created_at, updated_at)
        VALUES (?, ?, 1, 1.0, 0, ?, ?)
        """,
        (session_id, default_scope, now, now)
    )
    conn.commit()
    return {
        "session_id": session_id,
        "active_scope": default_scope,
        "scope_epoch": 1,
        "scope_confidence": 1.0,
        "last_seq": 0,
        "last_cwd": None
    }

def append_event(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    origin: str,
    turn_id: Optional[str] = None,
    root_event_id: Optional[str] = None,
    fact_kind: Optional[str] = None,
    fact_key: Optional[str] = None,
    fact_value: Optional[str] = None
) -> Tuple[str, int]:
    """Append event to WAL and atomically update last_seq."""
    ensure_session(conn, session_id)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    content_hash = compute_content_hash(content)
    authority = get_authority_for_role(origin, role)
    
    # Increment seq
    cursor = conn.execute(
        "UPDATE sessions SET last_seq = last_seq + 1, updated_at = ? WHERE session_id = ? RETURNING last_seq",
        (now, session_id)
    )
    res = cursor.fetchone()
    seq = res[0] if res else 1
    
    conn.execute(
        """
        INSERT INTO events (
            event_id, session_id, seq, turn_id, origin, role,
            content, content_hash, root_event_id, authority,
            effective_at, created_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            event_id, session_id, seq, turn_id, origin, role,
            content, content_hash, root_event_id or event_id, authority,
            now, now
        )
    )
    
    # Also queue in outbox for asynchronous replication to Borg
    if origin == "direct_user":
        conn.execute(
            """
            INSERT OR IGNORE INTO outbox (event_id, payload, destination, state, created_at)
            VALUES (?, ?, 'borg_broker', 'pending', ?)
            """,
            (event_id, content, now)
        )
        
        # Add to SessionOverlay as active current statement
        entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO overlay (
                entry_id, session_id, kind, key, value,
                source_event_id, seq, authority, status, created_at
            ) VALUES (?, ?, 'statement', 'user_utterance', ?, ?, ?, ?, 'active', ?)
            """,
            (entry_id, session_id, content, event_id, seq, authority, now)
        )
    elif (origin in ("runtime_tool_verified", "tool_verified", "tool_observation", "tool", "jit_compactor")) and fact_key:
        entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
        kind = fact_kind or ("verified_fact" if authority >= 1.0 else "tool_observation")
        conn.execute(
            """
            INSERT INTO overlay (
                entry_id, session_id, kind, key, value,
                source_event_id, seq, authority, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (entry_id, session_id, kind, fact_key, fact_value or content, event_id, seq, authority, now)
        )
        
    conn.commit()
    return event_id, seq

def get_active_overlays(conn: sqlite3.Connection, session_id: str, limit: int = 10) -> List[Dict]:
    """Retrieve active session overlay items (Read-Your-Own-Writes / Invariant I2)."""
    cursor = conn.execute(
        """
        SELECT entry_id, session_id, kind, key, value, source_event_id, seq, authority, created_at
        FROM overlay
        WHERE session_id = ? AND status = 'active'
        ORDER BY seq DESC
        LIMIT ?
        """,
        (session_id, limit)
    )
    return [dict(r) for r in cursor.fetchall()]

def get_active_facts(conn: sqlite3.Connection, session_id: str, limit: int = 30) -> List[Dict]:
    """Active verified facts, queried separately so user statements cannot crowd them out."""
    cursor = conn.execute(
        """
        SELECT key, value FROM overlay
        WHERE session_id = ? AND status = 'active' AND kind = 'verified_fact'
        ORDER BY seq DESC
        LIMIT ?
        """,
        (session_id, limit)
    )
    return [dict(r) for r in cursor.fetchall()]

def get_latest_direct_user_message(conn: sqlite3.Connection, session_id: str) -> Optional[str]:
    """Retrieve the most recent genuine direct_user message from WAL."""
    cursor = conn.execute(
        """
        SELECT content FROM events
        WHERE session_id = ? AND origin = 'direct_user' AND status = 'active'
        ORDER BY seq DESC LIMIT 1
        """,
        (session_id,)
    )
    row = cursor.fetchone()
    return row[0] if row else None

def update_session_cwd(conn: sqlite3.Connection, session_id: str, cwd: str) -> None:
    """Persist current working directory for session scope tracking."""
    if not cwd:
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        conn.execute("UPDATE sessions SET last_cwd = ?, updated_at = ? WHERE session_id = ?", (cwd, now, session_id))
        conn.commit()
    except Exception:
        pass

def get_session_cwd(conn: sqlite3.Connection, session_id: str) -> Optional[str]:
    """Last known working directory for this session.

    Prefers the cwd observed from terminal tool output (overlay). Until a terminal tool runs
    (first turn, or a delegated child that only uses file tools) it falls back to the cwd
    Hermes recorded for this exact session id in ~/.hermes/state.db. That value is
    session-scoped, so it cannot bleed context across sessions the way process cwd would.
    """
    try:
        cursor = conn.execute("SELECT last_cwd FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return get_hermes_session_cwd(session_id)


def get_hermes_session_cwd(session_id: str) -> Optional[str]:
    """cwd stored by Hermes for this session (read-only, fail-open to None)."""
    db_path = os.environ.get("HERMES_STATE_DB") or os.path.expanduser("~/.hermes/state.db")
    if not session_id or not os.path.exists(db_path):
        return None
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)) as hermes_db:
            row = hermes_db.execute("SELECT cwd FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error:
        return None


