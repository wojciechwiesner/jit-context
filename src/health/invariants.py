"""Invariant evaluation, trust contracts, and claims registry for Hermes JIT Context OS (I1..I10)."""

import sqlite3
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional, Callable

from l0.overlay import append_event, ensure_session, get_active_overlays
from l0.epistemics import get_authority_for_role, cap_derived_authority
from l1.scope import resolve_scope
from l2.circuit_breaker import CircuitBreaker


class InvariantStatus(str, Enum):
    """Allowed evaluation statuses for architectural invariants."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.value.upper() == other.upper()
        if isinstance(other, InvariantStatus):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


class EvidenceStatus(str, Enum):
    """Lifecycle statuses for tool and runtime evidence (authority is not truth)."""
    OBSERVED_SUCCESS = "observed_success"
    OBSERVED_FAILURE = "observed_failure"
    UNKNOWN = "unknown"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


@dataclass(frozen=True)
class InvariantContract:
    """Formal trust contract and verification mapping for an invariant."""
    id: str
    contract_id: str
    name: str
    description: str
    test_ref: str
    allowed_statuses: Tuple[InvariantStatus, ...] = (
        InvariantStatus.PASS,
        InvariantStatus.FAIL,
        InvariantStatus.SKIP,
        InvariantStatus.UNKNOWN,
    )


INVARIANTS_REGISTRY: Dict[str, InvariantContract] = {
    "I1": InvariantContract(
        id="I1",
        contract_id="INV-USER-OVERRIDE",
        name="Direct User Wins",
        description="Direct user statement overrides older facts, assistant hypotheses, and background memory.",
        test_ref="src/tests/test_invariants.py::test_i1_user_overrides_l1_and_l2",
    ),
    "I2": InvariantContract(
        id="I2",
        contract_id="INV-L0-RYOW",
        name="Read-Your-Own-Writes",
        description="L0 writes are immediately readable within the session without remote service dependency.",
        test_ref="src/tests/test_invariants.py::test_i2_ryow_when_borg_offline",
    ),
    "I3": InvariantContract(
        id="I3",
        contract_id="INV-ANTI-SELF-POISON",
        name="Assistant Authority Zero",
        description="Assistant role and origin authority is strictly 0.0 to prevent self-poisoning.",
        test_ref="src/tests/test_invariants.py::test_i3_assistant_authority_is_zero",
    ),
    "I4": InvariantContract(
        id="I4",
        contract_id="INV-AUTHORITY-CAP",
        name="No Authority Laundering",
        description="Derived authority cannot exceed root authority; synthetic harness cannot assume user authority.",
        test_ref="src/tests/test_invariants.py::test_i4_derived_authority_is_capped",
    ),
    "I5": InvariantContract(
        id="I5",
        contract_id="INV-SCOPE-HYSTERESIS",
        name="Scope Hysteresis & Isolation",
        description="Cross-project references do not switch active scope; project paths are strictly bounded.",
        test_ref="src/tests/test_invariants.py::test_i5_cross_project_lookup_does_not_switch_scope",
    ),
    "I6": InvariantContract(
        id="I6",
        contract_id="INV-L2-FAIL-OPEN",
        name="Fail-Open Circuit Breaker",
        description="L2 circuit breaker trips after consecutive failures without holding database locks.",
        test_ref="src/tests/test_invariants.py::test_i6_circuit_breaker_skips_network_when_open",
    ),
    "I7": InvariantContract(
        id="I7",
        contract_id="INV-ORDERING-IDEMPOTENT",
        name="Monotonic Ordering & Delivery Idempotence",
        description="Sequence numbers increment monotonically; re-delivery with identical delivery ID is idempotent.",
        test_ref="src/tests/test_invariants.py::test_i7_old_sequence_cannot_resurrect_state",
    ),
    "I8": InvariantContract(
        id="I8",
        contract_id="INV-PROVENANCE-BOUNDS",
        name="Independent Provenance & Budget Bounds",
        description="Direct user origin is distinguished from external/tool origins; capsule adheres to hard budget.",
        test_ref="src/tests/test_invariants.py::test_i8_same_root_is_counted_once",
    ),
    "I9": InvariantContract(
        id="I9",
        contract_id="INV-MEMORY-NON-AUTHORIZING",
        name="Memory Non-Authorizing",
        description="Ingested memory and external data cannot authorize destructive mutations or execute state changes.",
        test_ref="src/tests/test_invariants.py::test_i9_memory_cannot_authorize_mutation",
    ),
    "I10": InvariantContract(
        id="I10",
        contract_id="INV-CANON-IMMUTABLE",
        name="Immutable Canon & Typed Evidence",
        description="External content cannot write to CANON; tool evidence requires verified status and resource binding.",
        test_ref="src/tests/test_invariants.py::test_i10_external_text_cannot_write_canon",
    ),
}


def check_i1_direct_user_wins(conn: sqlite3.Connection, session_id: str = "test_i1") -> InvariantStatus:
    """I1: Direct user statement overrides older facts."""
    try:
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        ensure_session(conn, session_id)
        append_event(conn, session_id, "user", "Ustaw port 8005", "direct_user")
        overlays = get_active_overlays(conn, session_id)
        passed = any("8005" in o["value"] for o in overlays)
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i2_ryow(conn: sqlite3.Connection, session_id: str = "test_i2") -> InvariantStatus:
    """I2: Read-Your-Own-Writes immediately accessible from L0 without remote network."""
    try:
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        ensure_session(conn, session_id)
        _, seq = append_event(conn, session_id, "user", "Nowy sekretny klucz ABC", "direct_user")
        overlays = get_active_overlays(conn, session_id)
        passed = any("ABC" in o["value"] for o in overlays) and seq > 0
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i3_assistant_authority_zero() -> InvariantStatus:
    """I3: Assistant authority is always 0.0 (anti-self-poisoning)."""
    try:
        auth = get_authority_for_role(origin="assistant", role="assistant")
        return InvariantStatus.PASS if auth == 0.0 else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i4_no_authority_laundering() -> InvariantStatus:
    """I4: Derived authority cannot exceed root authority."""
    try:
        capped = cap_derived_authority(root_authority=0.5, claimed_authority=0.99)
        return InvariantStatus.PASS if capped == 0.5 else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i5_scope_hysteresis() -> InvariantStatus:
    """I5: Single cross-project mention does not switch active scope."""
    try:
        active, retrieval, _, _ = resolve_scope("Jak robiliśmy w InvoiceFlow?", "hermes")
        passed = active == "hermes" and "invoiceflow" in retrieval
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i6_fail_open(conn: sqlite3.Connection) -> InvariantStatus:
    """I6: Circuit breaker trips after consecutive failures and prevents blocking."""
    try:
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        cb = CircuitBreaker("test_cb_i6")
        cb.record_failure(conn)
        cb.record_failure(conn)
        cb.record_failure(conn)
        passed = not cb.can_attempt(conn)
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i7_ordering_idempotence(conn: sqlite3.Connection, session_id: str = "test_i7") -> InvariantStatus:
    """I7: Sequence numbers increment monotonically."""
    try:
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        ensure_session(conn, session_id)
        _, seq1 = append_event(conn, session_id, "user", "Pierwszy", "direct_user")
        _, seq2 = append_event(conn, session_id, "user", "Drugi", "direct_user")
        passed = seq2 > seq1
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i8_independent_provenance() -> InvariantStatus:
    """I8: Direct user origin is distinguished from external/derived."""
    try:
        user_auth = get_authority_for_role(origin="direct_user", role="user")
        ext_auth = get_authority_for_role(origin="external", role="user")
        passed = user_auth > ext_auth
        return InvariantStatus.PASS if passed else InvariantStatus.FAIL
    except Exception:
        return InvariantStatus.FAIL


def check_i9_memory_cannot_authorize() -> InvariantStatus:
    """I9: Ingested memory statements are non-authorizing for direct destructive operations."""
    try:
        mem_auth = get_authority_for_role(origin="external", role="system")
        if mem_auth >= 1.0:
            return InvariantStatus.FAIL
        return InvariantStatus.PASS
    except Exception:
        return InvariantStatus.FAIL


def check_i10_no_canon_promotion() -> InvariantStatus:
    """I10: External content cannot write to CANON."""
    try:
        ext_auth = get_authority_for_role(origin="external", role="user")
        if ext_auth > 0.5:
            return InvariantStatus.FAIL
        return InvariantStatus.PASS
    except Exception:
        return InvariantStatus.FAIL


def evaluate_all_invariants(conn: sqlite3.Connection) -> Dict[str, InvariantStatus]:
    """Evaluate all invariants I1..I10 and return dictionary of InvariantStatus values."""
    return {
        "I1": check_i1_direct_user_wins(conn),
        "I2": check_i2_ryow(conn),
        "I3": check_i3_assistant_authority_zero(),
        "I4": check_i4_no_authority_laundering(),
        "I5": check_i5_scope_hysteresis(),
        "I6": check_i6_fail_open(conn),
        "I7": check_i7_ordering_idempotence(conn),
        "I8": check_i8_independent_provenance(),
        "I9": check_i9_memory_cannot_authorize(),
        "I10": check_i10_no_canon_promotion(),
    }
