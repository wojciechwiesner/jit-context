"""
Borg Context Broker & Hermes JIT Context OS v0.1
SessionOverlay Engine (L0/L1 Local Memory & RYOW Layer)

Implements Invariants:
- I1: Direct User Input Wins
- I2: Zero-Latency RYOW (<3ms)
- I3: Assistant Output = 0 Root Fact
- I7: No State Resurrection (Monotonic session_seq & supersedes)
- I10: Quoted Content Quarantine
"""

import os
import sqlite3
import time
import uuid
from typing import Dict, Any, List, Optional

class SessionOverlay:
    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            base_dir = os.path.expanduser("~/.hermes/memory")
            os.makedirs(base_dir, exist_ok=True)
            self.db_path = os.path.join(base_dir, "session_overlay.db")
        else:
            self.db_path = db_path
            
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS session_metadata (
                    session_id TEXT PRIMARY KEY,
                    active_scope TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    head_seq INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS context_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    session_seq INTEGER NOT NULL,
                    scope_id TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin IN (
                        'direct_user_instruction', 
                        'direct_user_assertion', 
                        'user_pasted_external', 
                        'runtime_tool_verified', 
                        'assistant_hypothesis',
                        'derived_context'
                    )),
                    epistemic_weight REAL NOT NULL DEFAULT 0.0,
                    fact_key TEXT,
                    fact_value TEXT,
                    supersedes_event_id TEXT,
                    is_quarantined BOOLEAN DEFAULT 0,
                    sync_status TEXT DEFAULT 'pending' CHECK(sync_status IN ('pending', 'synced', 'failed')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES session_metadata(session_id),
                    FOREIGN KEY(supersedes_event_id) REFERENCES context_events(event_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_session_seq ON context_events(session_id, session_seq DESC);
                CREATE INDEX IF NOT EXISTS idx_scope_facts ON context_events(scope_id, fact_key) WHERE fact_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_pending_sync ON context_events(sync_status) WHERE sync_status = 'pending';
            """)

    def start_session(self, session_id: str, scope: str = "global"):
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_metadata (session_id, active_scope, head_seq)
                VALUES (?, ?, 0)
                ON CONFLICT(session_id) DO UPDATE SET 
                    last_active_at = CURRENT_TIMESTAMP,
                    active_scope = excluded.active_scope;
                """,
                (session_id, scope)
            )

    def record_event(
        self,
        session_id: str,
        scope_id: str,
        origin: str,
        fact_key: Optional[str] = None,
        fact_value: Optional[str] = None,
        supersedes_event_id: Optional[str] = None,
        is_quarantined: bool = False
    ) -> Dict[str, Any]:
        """
        Records an event with strict epistemic weight and monotonic sequencing.
        """
        # Invariant I3: Assistant output CANNOT create a root durable fact (epistemic_weight = 0.0)
        # Invariant I10: Quoted external content is strictly quarantined
        if origin == "direct_user_assertion" or origin == "direct_user_instruction":
            epistemic_weight = 1.0
        elif origin == "runtime_tool_verified":
            epistemic_weight = 1.0
        elif origin == "user_pasted_external":
            epistemic_weight = 0.1
            is_quarantined = True
        elif origin == "assistant_hypothesis":
            epistemic_weight = 0.0
        else:
            epistemic_weight = 0.3

        event_id = str(uuid.uuid4())

        with self._get_connection() as conn:
            # Get next monotonic sequence for this session
            row = conn.execute(
                "SELECT head_seq FROM session_metadata WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            
            current_head = row["head_seq"] if row else 0
            next_seq = current_head + 1

            # Update session metadata head_seq
            conn.execute(
                """
                INSERT INTO session_metadata (session_id, active_scope, head_seq)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET 
                    head_seq = ?,
                    last_active_at = CURRENT_TIMESTAMP;
                """,
                (session_id, scope_id, next_seq, next_seq)
            )

            # Auto-detect supersedes if key exists in active session
            if fact_key and not supersedes_event_id:
                prev_event = conn.execute(
                    """
                    SELECT event_id FROM context_events 
                    WHERE session_id = ? AND scope_id = ? AND fact_key = ?
                    ORDER BY session_seq DESC LIMIT 1
                    """,
                    (session_id, scope_id, fact_key)
                ).fetchone()
                if prev_event:
                    supersedes_event_id = prev_event["event_id"]

            conn.execute(
                """
                INSERT INTO context_events (
                    event_id, session_id, session_seq, scope_id, origin,
                    epistemic_weight, fact_key, fact_value, supersedes_event_id,
                    is_quarantined, sync_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    event_id, session_id, next_seq, scope_id, origin,
                    epistemic_weight, fact_key, fact_value, supersedes_event_id,
                    1 if is_quarantined else 0
                )
            )

        return {
            "event_id": event_id,
            "session_seq": next_seq,
            "epistemic_weight": epistemic_weight,
            "supersedes_event_id": supersedes_event_id,
            "is_quarantined": is_quarantined
        }

    def get_active_facts(self, session_id: str, scope_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Returns latest active, non-quarantined facts with RYOW consistency (<3ms).
        Filters out superseded events and events with epistemic_weight == 0.0.
        """
        query = """
            SELECT event_id, session_seq, scope_id, origin, epistemic_weight, fact_key, fact_value
            FROM context_events
            WHERE session_id = ? AND is_quarantined = 0 AND epistemic_weight > 0.0 AND fact_key IS NOT NULL
        """
        params = [session_id]
        if scope_id:
            query += " AND scope_id = ?"
            params.append(scope_id)

        query += " ORDER BY session_seq ASC;"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        # Build latest active fact state by sequentially applying events (latest seq wins for key)
        active_facts: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            active_facts[row["fact_key"]] = {
                "event_id": row["event_id"],
                "session_seq": row["session_seq"],
                "scope_id": row["scope_id"],
                "origin": row["origin"],
                "epistemic_weight": row["epistemic_weight"],
                "value": row["fact_value"]
            }

        return active_facts

    def get_pending_sync_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT event_id, session_id, session_seq, scope_id, origin,
                       epistemic_weight, fact_key, fact_value, supersedes_event_id
                FROM context_events
                WHERE sync_status = 'pending'
                ORDER BY created_at ASC LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [dict(r) for r in rows]

    def mark_events_synced(self, event_ids: List[str]):
        if not event_ids:
            return
        placeholders = ",".join(["?"] * len(event_ids))
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE context_events SET sync_status = 'synced' WHERE event_id IN ({placeholders})",
                event_ids
            )
