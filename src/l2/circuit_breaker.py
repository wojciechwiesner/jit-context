"""Circuit Breaker for L2 Remote Broker (Invariant I6)."""

import time
import sqlite3
from typing import Optional, Tuple
from config import CB_CONSECUTIVE_FAILURES_THRESHOLD, CB_COOLDOWN_SECONDS

class CircuitBreaker:
    def __init__(self, provider: str = "borg_broker"):
        self.provider = provider

    def _ensure_row(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO provider_state (provider, state, consecutive_failures, latency_ema) VALUES (?, 'closed', 0, 100.0)",
            (self.provider,)
        )

    def get_state(self, conn: sqlite3.Connection) -> Tuple[str, int, Optional[float]]:
        """Returns (state, consecutive_failures, opened_at_timestamp)."""
        self._ensure_row(conn)
        cursor = conn.execute(
            "SELECT state, consecutive_failures, opened_at FROM provider_state WHERE provider = ?",
            (self.provider,)
        )
        row = cursor.fetchone()
        if not row:
            return "closed", 0, None
            
        state = row["state"]
        failures = row["consecutive_failures"]
        opened_at_str = row["opened_at"]
        opened_at = None
        if opened_at_str:
            try:
                opened_at = float(opened_at_str)
            except ValueError:
                opened_at = None
                
        # Check if cooldown expired in OPEN state -> transition to HALF_OPEN
        if state == "open" and opened_at is not None:
            if time.time() - opened_at > CB_COOLDOWN_SECONDS:
                state = "half_open"
                conn.execute(
                    "UPDATE provider_state SET state = 'half_open' WHERE provider = ?",
                    (self.provider,)
                )
                conn.commit()
                
        return state, failures, opened_at

    def can_attempt(self, conn: sqlite3.Connection) -> bool:
        """Returns True if call should be attempted, False if circuit is OPEN."""
        state, _, _ = self.get_state(conn)
        return state in ("closed", "half_open")

    def record_success(self, conn: sqlite3.Connection, latency_ms: float) -> None:
        self._ensure_row(conn)
        now_ts = str(time.time())
        conn.execute(
            """
            UPDATE provider_state
            SET state = 'closed', consecutive_failures = 0, last_success = ?, last_attempt = ?,
                latency_ema = 0.8 * latency_ema + 0.2 * ?
            WHERE provider = ?
            """,
            (now_ts, now_ts, latency_ms, self.provider)
        )
        conn.commit()

    def record_failure(self, conn: sqlite3.Connection) -> None:
        self._ensure_row(conn)
        now_ts = str(time.time())
        state, failures, _ = self.get_state(conn)
        new_failures = failures + 1
        
        if new_failures >= CB_CONSECUTIVE_FAILURES_THRESHOLD or state == "half_open":
            conn.execute(
                """
                UPDATE provider_state
                SET state = 'open', consecutive_failures = ?, opened_at = ?, last_attempt = ?
                WHERE provider = ?
                """,
                (new_failures, now_ts, now_ts, self.provider)
            )
        else:
            conn.execute(
                """
                UPDATE provider_state
                SET consecutive_failures = ?, last_attempt = ?
                WHERE provider = ?
                """,
                (new_failures, now_ts, self.provider)
            )
        conn.commit()
