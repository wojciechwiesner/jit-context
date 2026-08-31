"""RecentTurnFence for deduplicated recent context injection across compressions."""

import hashlib
import sqlite3
from typing import List, Dict, Set

def compute_content_hash(text: str) -> str:
    cleaned = text.strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]

def get_missing_recent_turns(
    conn: sqlite3.Connection,
    session_id: str,
    transcript_hashes: Set[str],
    limit: int = 12
) -> List[Dict]:
    """Returns direct_user events from L0 that are NOT present in the active transcript.
    Prevents duplicate token overhead while preserving context lost during compression.
    """
    cursor = conn.execute(
        """
        SELECT event_id, seq, role, content, content_hash, authority, created_at
        FROM events
        WHERE session_id = ? AND role = 'user' AND status = 'active'
        ORDER BY seq DESC
        LIMIT ?
        """,
        (session_id, limit)
    )
    rows = cursor.fetchall()
    
    missing = []
    for r in reversed(rows):
        if r["content_hash"] not in transcript_hashes:
            missing.append(dict(r))
            
    return missing
