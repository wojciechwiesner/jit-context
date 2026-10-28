"""Disposable diagnostic storage: synthetic users never enter live memory or outbox."""

import sqlite3
from contextlib import closing
from typing import Dict

from health import invariants as checks
from health.invariants import InvariantStatus
from l0.db import _init_db_conn


def diagnostic_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _init_db_conn(connection)
    return connection


def run_invariant_self_tests() -> Dict[str, InvariantStatus]:
    with closing(diagnostic_connection()) as connection:
        return {
            "I1": checks.check_i1_direct_user_wins(connection),
            "I2": checks.check_i2_ryow(connection),
            "I3": checks.check_i3_assistant_authority_zero(),
            "I4": checks.check_i4_no_authority_laundering(),
            "I5": checks.check_i5_scope_hysteresis(),
            "I6": checks.check_i6_fail_open(connection),
            "I7": checks.check_i7_ordering_idempotence(connection),
            "I8": checks.check_i8_independent_provenance(),
            "I9": checks.check_i9_memory_cannot_authorize(),
            "I10": checks.check_i10_no_canon_promotion(),
            "I11": checks.check_i11_no_epistemically_equivalent_retry(),
        }


def evaluate_all_invariants(conn: sqlite3.Connection) -> Dict[str, InvariantStatus]:
    """Run synthetic invariants in disposable storage, never against the caller DB.
    `conn` is accepted for API compatibility and deliberately ignored."""
    return run_invariant_self_tests()
