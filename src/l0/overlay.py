"""SessionOverlay & WAL append logic implementing Invariants I1, I2, I7."""

import time
import uuid
import sqlite3
from typing import Optional, List, Dict, Tuple
from l0.recent_fence import compute_content_hash
from l0.epistemics import get_authority_for_role

def ensure_session(
    conn: sqlite3.Connection,
    session_id: str,
    default_scope: str = "general"
) -> Dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
        "last_seq": 0
    }

def append_event(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    origin: str,
    turn_id: Optional[str] = None,
    root_event_id: Optional[str] = None
) -> Tuple[str, int]:
    """Append event to WAL and atomically update last_seq."""
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
        
    conn.commit()
    return event_id, seq

def get_active_overlays(conn: sqlite3.Connection, session_id: str, limit: int = 5) -> List[Dict]:
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
