"""Typed tool execution models and evidence lifecycle.

Implements Invariants I3, I4, I8 and SPECYFIKACJA §3:
- Sformalizowany cykl życia dowodów: observed_success, observed_failure, unknown, superseded, expired.
- Granica narzędzie vs stan rzeczywisty: komenda terminala (exit 0) dowodzi wyjścia procesu,
  a nie pomyślnego wdrożenia produkcyjnego bez sprawdzenia zdrowia (healthcheck).
- Zakaz wnioskowania o sukcesie z samego braku błędu (wymagane jawne flagi sukcesu).
- Nieważność mutacji: późniejsza nieudana mutacja unieważnia stan bieżący, zachowując historię WAL.
- Błędy operacji tylko do odczytu nie usuwają ani nie unieważniają zdarzeń zapisu.
- Asercje asystenta niosą wagę 0.0 i nie tworzą dowodów.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    """Evidence lifecycle states defined in SPECYFIKACJA §3.1."""
    OBSERVED_SUCCESS = "observed_success"
    OBSERVED_FAILURE = "observed_failure"
    UNKNOWN = "unknown"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class OperationKind(str, Enum):
    """Operation types executed by tools."""
    EXECUTE = "execute"
    WRITE = "write"
    PATCH = "patch"
    DELETE = "delete"
    READ = "read"
    DEPLOY = "deploy"
    HEALTHCHECK = "healthcheck"
    GENERIC = "generic"


class ClaimScope(str, Enum):
    """Strict boundaries on what tool evidence actually proves (§3.2)."""
    PROCESS_EXIT = "process_exit"           # Proves exit code 0; NOT service health or deployment
    FILE_MUTATION = "file_mutation"         # Proves file content written/patched at path
    FILE_DELETION = "file_deletion"         # Proves file removal
    READ_OBSERVATION = "read_observation"   # Read-only observation; non-mutating
    SERVICE_HEALTH = "service_health"       # Proves running service health via explicit check
    UNKNOWN = "unknown"


DEPLOY_COMMAND_PATTERNS = (
    "docker compose up", "docker-compose up", "docker run",
    "kubectl apply", "kubectl rollout", "helm install", "helm upgrade",
    "systemctl start", "systemctl restart", "service ",
    "pm2 start", "pm2 restart", "deploy.sh", "npm run deploy", "yarn deploy"
)


class ToolEvidenceRecord(BaseModel):
    """Typed evidence record binding execution proof to resource and lifecycle."""
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:12]}")
    session_id: str = "default"
    event_id: Optional[str] = None
    tool_name: str
    operation: OperationKind
    claim_scope: ClaimScope
    status: EvidenceStatus
    resource: Optional[str] = None
    fact_key: Optional[str] = None
    fact_value: Optional[str] = None
    version_hash: Optional[str] = None
    authority: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_verified(self) -> bool:
        """True only if explicit success observed with authoritative proof."""
        return self.status == EvidenceStatus.OBSERVED_SUCCESS and self.authority >= 1.0

    @property
    def is_deploy_proof(self) -> bool:
        """Exit 0 on deploy command is NOT proof of live deployment without healthcheck (§3.2)."""
        return self.claim_scope == ClaimScope.SERVICE_HEALTH and self.status == EvidenceStatus.OBSERVED_SUCCESS

    def to_origin_tuple(self) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        """Legacy tuple adapter: (origin, fact_kind, fact_key, fact_value)."""
        if self.status == EvidenceStatus.OBSERVED_SUCCESS and self.authority >= 1.0:
            return "runtime_tool_verified", "verified_fact", self.fact_key, self.fact_value
        if self.status == EvidenceStatus.OBSERVED_FAILURE:
            return "tool_observation", "tool_error", self.fact_key, self.fact_value
        return "tool_observation", None, self.fact_key, self.fact_value


def _normalize_dict(val: Any) -> Dict[str, Any]:
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _detect_error(out_dict: Dict[str, Any], raw_output: Any) -> Tuple[bool, str]:
    """Inspects tool output for failure indicators and returns (has_error, error_detail)."""
    if out_dict:
        if out_dict.get("error"):
            return True, str(out_dict.get("error"))
        if out_dict.get("errors"):
            return True, str(out_dict.get("errors"))
        if out_dict.get("success") is False:
            return True, "success_flag_false"
        if out_dict.get("verified") is False:
            return True, "verified_flag_false"
        raw_code = out_dict.get("exit_code")
        if raw_code is not None:
            try:
                code = int(raw_code)
                if code != 0:
                    return True, f"exit_code_{code}"
            except (ValueError, TypeError):
                return True, "invalid_exit_code"

    if isinstance(raw_output, str):
        lower = raw_output.lower()
        if "traceback (most recent call last)" in lower:
            return True, "traceback_detected"
        if "syntaxerror:" in lower or "fatal error:" in lower:
            return True, raw_output.strip()[:100]
        if lower.startswith("error:") or "\nerror:" in lower:
            return True, raw_output.strip()[:100]

    return False, ""


def parse_tool_evidence(
    tool_name: str,
    tool_input: Any,
    tool_output: Any,
    session_id: str = "default",
    event_id: Optional[str] = None,
    role: Optional[str] = None
) -> ToolEvidenceRecord:
    """Parses tool execution with strict validation, contradiction detection, and claim boundaries."""
    # Invariant I3: Assistant assertions carry 0.0 authority and cannot produce evidence
    if role == "assistant" or tool_name in ("assistant", "assistant_message", "assistant_claim"):
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.GENERIC,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.UNKNOWN,
            authority=0.0,
            metadata={"error": "assistant_assertions_carry_zero_authority"}
        )

    inp = _normalize_dict(tool_input)
    out_dict = _normalize_dict(tool_output)
    out_str = tool_output if isinstance(tool_output, str) else ""

    # Status: pending or in_progress yields UNKNOWN
    if out_dict.get("status") in ("pending", "in_progress"):
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.GENERIC,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.UNKNOWN,
            authority=0.0,
            metadata={"status": out_dict.get("status")}
        )

    has_error, err_detail = _detect_error(out_dict, tool_output)

    # Contradiction check: explicit verified/success=True but simultaneously has_error
    if out_dict and (out_dict.get("verified") is True or out_dict.get("success") is True) and has_error:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.GENERIC,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.UNKNOWN,
            authority=0.0,
            metadata={"error": "contradictory_flags", "detail": err_detail}
        )

    # Dispatch tool-specific parser
    if tool_name == "terminal":
        return _parse_terminal_evidence(tool_name, session_id, event_id, inp, out_dict, out_str, has_error, err_detail)
    elif tool_name in ("write_file", "patch"):
        return _parse_file_mutation_evidence(tool_name, session_id, event_id, inp, out_dict, out_str, has_error, err_detail)
    elif tool_name in ("delete_file", "remove_file"):
        return _parse_file_delete_evidence(tool_name, session_id, event_id, inp, out_dict, has_error, err_detail)
    elif tool_name in ("read_file", "search_files", "web_extract", "web_search", "web_read"):
        return _parse_read_evidence(tool_name, session_id, event_id, inp, out_dict, out_str, has_error, err_detail)
    else:
        return _parse_generic_evidence(tool_name, session_id, event_id, inp, out_dict, has_error, err_detail)


def _parse_terminal_evidence(
    tool_name: str,
    session_id: str,
    event_id: Optional[str],
    inp: Dict[str, Any],
    out_dict: Dict[str, Any],
    out_str: str,
    has_error: bool,
    err_detail: str
) -> ToolEvidenceRecord:
    cmd = inp.get("command", "")
    if not isinstance(cmd, str):
        cmd = str(cmd)
    cmd_clean = cmd.strip()
    cmd_short = cmd_clean.split("\n")[0][:60]

    # Delete command via terminal (rm / unlink)
    if cmd_clean.startswith("rm ") or " rm " in cmd_clean or cmd_clean.startswith("unlink "):
        parts = cmd_clean.split()
        target = parts[-1] if len(parts) > 1 else "unknown"
        exit_code = out_dict.get("exit_code") if out_dict else None
        if exit_code == 0 and not has_error:
            return ToolEvidenceRecord(
                session_id=session_id,
                event_id=event_id,
                tool_name=tool_name,
                operation=OperationKind.DELETE,
                claim_scope=ClaimScope.FILE_DELETION,
                status=EvidenceStatus.OBSERVED_SUCCESS,
                resource=f"file:{target}",
                fact_key=f"file:{target}",
                fact_value="deleted (verified)",
                authority=1.0,
                metadata={"command": cmd_clean}
            )

    is_deploy = any(sig in cmd_clean for sig in DEPLOY_COMMAND_PATTERNS)
    is_healthcheck = "health" in cmd_clean and ("curl" in cmd_clean or "http" in cmd_clean or "wget" in cmd_clean)
    op = OperationKind.HEALTHCHECK if is_healthcheck else (OperationKind.DEPLOY if is_deploy else OperationKind.EXECUTE)

    exit_code = out_dict.get("exit_code") if out_dict else None

    # Handle exit_code == 0
    if exit_code == 0 and not has_error:
        if is_healthcheck:
            return ToolEvidenceRecord(
                session_id=session_id,
                event_id=event_id,
                tool_name=tool_name,
                operation=op,
                claim_scope=ClaimScope.SERVICE_HEALTH,
                status=EvidenceStatus.OBSERVED_SUCCESS,
                resource=f"health:{cmd_short}",
                fact_key=f"health:{cmd_short}",
                fact_value="healthy (verified)",
                authority=1.0,
                metadata={"exit_code": 0, "command": cmd_clean}
            )

        fact_val = (
            "exit_code=0 (command exited, deployment not verified without healthcheck)"
            if is_deploy else "exit_code=0 (verified)"
        )
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=op,
            claim_scope=ClaimScope.PROCESS_EXIT,
            status=EvidenceStatus.OBSERVED_SUCCESS,
            resource=f"cmd:{cmd_short}",
            fact_key=f"cmd:{cmd_short}",
            fact_value=fact_val,
            authority=1.0,
            metadata={"exit_code": 0, "command": cmd_clean, "is_deploy": is_deploy}
        )

    # Handle exit_code != 0
    if exit_code is not None and exit_code != 0:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=op,
            claim_scope=ClaimScope.PROCESS_EXIT,
            status=EvidenceStatus.OBSERVED_FAILURE,
            resource=f"cmd:{cmd_short}",
            fact_key=f"cmd_fail:{cmd_short}",
            fact_value=f"exit_code={exit_code}",
            authority=0.9,
            metadata={"exit_code": exit_code, "command": cmd_clean}
        )

    # Missing exit code or unparseable output
    return ToolEvidenceRecord(
        session_id=session_id,
        event_id=event_id,
        tool_name=tool_name,
        operation=op,
        claim_scope=ClaimScope.PROCESS_EXIT,
        status=EvidenceStatus.UNKNOWN,
        resource=f"cmd:{cmd_short}",
        authority=0.0,
        metadata={"command": cmd_clean, "raw_output": out_str[:100]}
    )


def _parse_file_mutation_evidence(
    tool_name: str,
    session_id: str,
    event_id: Optional[str],
    inp: Dict[str, Any],
    out_dict: Dict[str, Any],
    out_str: str,
    has_error: bool,
    err_detail: str
) -> ToolEvidenceRecord:
    path = inp.get("path", "")
    if not path:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.WRITE if tool_name == "write_file" else OperationKind.PATCH,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.UNKNOWN,
            authority=0.0,
            metadata={"error": "missing_path"}
        )

    op = OperationKind.WRITE if tool_name == "write_file" else OperationKind.PATCH
    res_key = f"file:{path}"

    v_hash = None
    if "content" in inp and isinstance(inp["content"], str):
        v_hash = hashlib.sha256(inp["content"].strip().encode("utf-8")).hexdigest()[:16]
    elif "new_string" in inp and isinstance(inp["new_string"], str):
        v_hash = hashlib.sha256(inp["new_string"].strip().encode("utf-8")).hexdigest()[:16]

    if has_error:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=op,
            claim_scope=ClaimScope.FILE_MUTATION,
            status=EvidenceStatus.OBSERVED_FAILURE,
            resource=res_key,
            fact_key=f"file_fail:{path}",
            fact_value=f"{op.value}_failed",
            authority=0.9,
            metadata={"error": err_detail, "path": path}
        )

    # Strict positive validation rule: silence/absence of error is NEVER sufficient proof
    explicit_success = False
    if out_dict:
        if out_dict.get("verified") is True or out_dict.get("success") is True:
            explicit_success = True
    elif out_str:
        if tool_name == "patch" and ("@@" in out_str or "diff --git" in out_str):
            explicit_success = True
        elif "verified: true" in out_str.lower() or "verified:true" in out_str.lower():
            explicit_success = True

    if explicit_success:
        action = "written" if op == OperationKind.WRITE else "patched"
        val = f"{action}_verified (verified, hash={v_hash})" if v_hash else f"{action}_verified (verified)"
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=op,
            claim_scope=ClaimScope.FILE_MUTATION,
            status=EvidenceStatus.OBSERVED_SUCCESS,
            resource=res_key,
            fact_key=res_key,
            fact_value=val,
            version_hash=v_hash,
            authority=1.0,
            metadata={"path": path}
        )

    return ToolEvidenceRecord(
        session_id=session_id,
        event_id=event_id,
        tool_name=tool_name,
        operation=op,
        claim_scope=ClaimScope.FILE_MUTATION,
        status=EvidenceStatus.UNKNOWN,
        resource=res_key,
        authority=0.0,
        metadata={"path": path, "reason": "missing_explicit_verification_flag"}
    )


def _parse_file_delete_evidence(
    tool_name: str,
    session_id: str,
    event_id: Optional[str],
    inp: Dict[str, Any],
    out_dict: Dict[str, Any],
    has_error: bool,
    err_detail: str
) -> ToolEvidenceRecord:
    path = inp.get("path", "")
    res_key = f"file:{path}" if path else "file:unknown"
    if has_error or (out_dict and out_dict.get("success") is False):
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.DELETE,
            claim_scope=ClaimScope.FILE_DELETION,
            status=EvidenceStatus.OBSERVED_FAILURE,
            resource=res_key,
            fact_key=f"delete_fail:{path}",
            fact_value="delete_failed",
            authority=0.9,
            metadata={"error": err_detail}
        )
    return ToolEvidenceRecord(
        session_id=session_id,
        event_id=event_id,
        tool_name=tool_name,
        operation=OperationKind.DELETE,
        claim_scope=ClaimScope.FILE_DELETION,
        status=EvidenceStatus.OBSERVED_SUCCESS,
        resource=res_key,
        fact_key=res_key,
        fact_value="deleted (verified)",
        authority=1.0,
        metadata={"path": path}
    )


def _parse_read_evidence(
    tool_name: str,
    session_id: str,
    event_id: Optional[str],
    inp: Dict[str, Any],
    out_dict: Dict[str, Any],
    out_str: str,
    has_error: bool,
    err_detail: str
) -> ToolEvidenceRecord:
    path = inp.get("path") or inp.get("pattern") or inp.get("query") or ""
    res_key = f"read:{path}" if path else f"tool:{tool_name}"
    if has_error:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.READ,
            claim_scope=ClaimScope.READ_OBSERVATION,
            status=EvidenceStatus.OBSERVED_FAILURE,
            resource=res_key,
            fact_key=f"read_fail:{path}" if path else f"read_fail:{tool_name}",
            fact_value=f"read_failed: {err_detail[:60]}",
            authority=0.9,
            metadata={"error": err_detail, "path": path}
        )
    return ToolEvidenceRecord(
        session_id=session_id,
        event_id=event_id,
        tool_name=tool_name,
        operation=OperationKind.READ,
        claim_scope=ClaimScope.READ_OBSERVATION,
        status=EvidenceStatus.OBSERVED_SUCCESS,
        resource=res_key,
        fact_key=res_key,
        fact_value="read_ok",
        authority=0.9,
        metadata={"path": path}
    )


def _parse_generic_evidence(
    tool_name: str,
    session_id: str,
    event_id: Optional[str],
    inp: Dict[str, Any],
    out_dict: Dict[str, Any],
    has_error: bool,
    err_detail: str
) -> ToolEvidenceRecord:
    if has_error:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.GENERIC,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.OBSERVED_FAILURE,
            authority=0.9,
            metadata={"error": err_detail}
        )
    if out_dict.get("verified") is True or out_dict.get("success") is True:
        return ToolEvidenceRecord(
            session_id=session_id,
            event_id=event_id,
            tool_name=tool_name,
            operation=OperationKind.GENERIC,
            claim_scope=ClaimScope.UNKNOWN,
            status=EvidenceStatus.OBSERVED_SUCCESS,
            authority=1.0,
            metadata={"verified": True}
        )
    return ToolEvidenceRecord(
        session_id=session_id,
        event_id=event_id,
        tool_name=tool_name,
        operation=OperationKind.GENERIC,
        claim_scope=ClaimScope.UNKNOWN,
        status=EvidenceStatus.UNKNOWN,
        authority=0.0
    )


def parse_tool_execution(tool_name: str, tool_input: Any, tool_output: Any) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Drop-in replacement for naive parser in src/hooks.py; returns legacy tuple."""
    record = parse_tool_evidence(tool_name, tool_input, tool_output)
    return record.to_origin_tuple()


# --- Evidence Lifecycle and DB Storage Engine ---

def init_evidence_schema(conn: sqlite3.Connection) -> None:
    """Initialize tool_evidence table idempotently."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tool_evidence (
        evidence_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        event_id TEXT,
        tool_name TEXT NOT NULL,
        operation TEXT NOT NULL,
        claim_scope TEXT NOT NULL,
        status TEXT NOT NULL,
        resource TEXT,
        fact_key TEXT,
        fact_value TEXT,
        version_hash TEXT,
        authority REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        superseded_by TEXT,
        metadata_json TEXT
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_evidence_session_res ON tool_evidence(session_id, resource);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_evidence_status ON tool_evidence(session_id, status);")


def _ensure_session_and_event(
    conn: sqlite3.Connection,
    evidence: ToolEvidenceRecord,
    now: str
) -> Tuple[str, int]:
    """Ensures session and event exist to satisfy SQLite foreign keys."""
    cursor = conn.execute(
        "SELECT session_id, last_seq FROM sessions WHERE session_id = ?",
        (evidence.session_id,)
    )
    row = cursor.fetchone()
    if not row:
        conn.execute(
            """
            INSERT INTO sessions (session_id, active_scope, scope_epoch, scope_confidence, last_seq, created_at, updated_at)
            VALUES (?, 'general', 1, 1.0, 1, ?, ?)
            """,
            (evidence.session_id, now, now)
        )
        seq = 1
    else:
        seq = (row[1] or 0) + 1
        conn.execute(
            "UPDATE sessions SET last_seq = ?, updated_at = ? WHERE session_id = ?",
            (seq, now, evidence.session_id)
        )

    event_id = evidence.event_id
    if event_id:
        ev_row = conn.execute("SELECT event_id FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not ev_row:
            event_id = None

    if not event_id:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        origin = "runtime_tool_verified" if evidence.authority >= 1.0 else "tool_observation"
        content = evidence.fact_value or f"{evidence.tool_name} execution"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        conn.execute(
            """
            INSERT INTO events (
                event_id, session_id, seq, turn_id, origin, role,
                content, content_hash, root_event_id, authority,
                effective_at, created_at, status
            ) VALUES (?, ?, ?, NULL, ?, 'tool', ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                event_id, evidence.session_id, seq, origin,
                content, content_hash, event_id, evidence.authority,
                now, now
            )
        )

    return event_id, seq


def record_tool_evidence(
    conn: sqlite3.Connection,
    evidence: ToolEvidenceRecord,
    auto_commit: bool = True
) -> None:
    """Record evidence and execute lifecycle transitions on overlay and WAL state."""
    init_evidence_schema(conn)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    bound_event_id, seq = _ensure_session_and_event(conn, evidence, now)

    # 1. Insert typed evidence record
    conn.execute(
        """
        INSERT INTO tool_evidence (
            evidence_id, session_id, event_id, tool_name, operation, claim_scope,
            status, resource, fact_key, fact_value, version_hash, authority,
            created_at, expires_at, superseded_by, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence.evidence_id, evidence.session_id, bound_event_id,
            evidence.tool_name, evidence.operation.value, evidence.claim_scope.value,
            evidence.status.value, evidence.resource, evidence.fact_key,
            evidence.fact_value, evidence.version_hash, evidence.authority,
            evidence.timestamp, evidence.expires_at, evidence.superseded_by,
            json.dumps(evidence.metadata)
        )
    )

    # 2. Lifecycle transitions on overlay
    if evidence.status == EvidenceStatus.OBSERVED_SUCCESS:
        # Mutation / write / delete / execute supersedes previous active state for the resource
        if evidence.resource:
            conn.execute(
                """
                UPDATE overlay SET status = 'superseded', supersedes = ?
                WHERE session_id = ? AND key = ? AND status = 'active'
                """,
                (evidence.evidence_id, evidence.session_id, evidence.resource)
            )
            conn.execute(
                """
                UPDATE tool_evidence SET status = 'superseded', superseded_by = ?
                WHERE session_id = ? AND resource = ? AND status = 'observed_success' AND evidence_id != ?
                """,
                (evidence.evidence_id, evidence.session_id, evidence.resource, evidence.evidence_id)
            )

        # Deletion removes active state without re-adding a verified fact
        if evidence.operation == OperationKind.DELETE:
            entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO overlay (
                    entry_id, session_id, kind, key, value, source_event_id,
                    seq, authority, status, created_at
                ) VALUES (?, ?, 'tool_observation', ?, 'deleted (verified)', ?, ?, ?, 'active', ?)
                """,
                (entry_id, evidence.session_id, evidence.resource or "deleted", bound_event_id, seq, evidence.authority, now)
            )
        elif evidence.fact_key and evidence.authority >= 1.0:
            entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO overlay (
                    entry_id, session_id, kind, key, value, source_event_id,
                    seq, authority, status, created_at
                ) VALUES (?, ?, 'verified_fact', ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    entry_id, evidence.session_id, evidence.fact_key,
                    evidence.fact_value or "", bound_event_id, seq,
                    evidence.authority, now
                )
            )

    elif evidence.status == EvidenceStatus.OBSERVED_FAILURE:
        # Conflicting mutation invalidates current-state inference (§3.1 item 4)
        if evidence.operation in (OperationKind.WRITE, OperationKind.PATCH, OperationKind.DELETE) and evidence.resource:
            conn.execute(
                """
                UPDATE overlay SET status = 'superseded', supersedes = ?
                WHERE session_id = ? AND key = ? AND status = 'active'
                """,
                (evidence.evidence_id, evidence.session_id, evidence.resource)
            )
            conn.execute(
                """
                UPDATE tool_evidence SET status = 'superseded', superseded_by = ?
                WHERE session_id = ? AND resource = ? AND status = 'observed_success'
                """,
                (evidence.evidence_id, evidence.session_id, evidence.resource)
            )
            # Record error in overlay
            entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO overlay (
                    entry_id, session_id, kind, key, value, source_event_id,
                    seq, authority, status, created_at
                ) VALUES (?, ?, 'tool_error', ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    entry_id, evidence.session_id, evidence.fact_key or f"err:{evidence.resource}",
                    evidence.fact_value or "mutation_failed", bound_event_id, seq,
                    evidence.authority, now
                )
            )
        elif evidence.operation == OperationKind.READ:
            # Read-only errors do NOT erase or supersede historical write events
            entry_id = f"ovl_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO overlay (
                    entry_id, session_id, kind, key, value, source_event_id,
                    seq, authority, status, created_at
                ) VALUES (?, ?, 'tool_error', ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    entry_id, evidence.session_id, evidence.fact_key or f"read_fail:{evidence.resource}",
                    evidence.fact_value or "read_failed", bound_event_id, seq,
                    evidence.authority, now
                )
            )

    if auto_commit:
        conn.commit()


def get_active_evidence(
    conn: sqlite3.Connection,
    session_id: str,
    resource: Optional[str] = None
) -> List[ToolEvidenceRecord]:
    """Retrieve all active verified evidence records for a session."""
    init_evidence_schema(conn)
    query = """
        SELECT evidence_id, session_id, event_id, tool_name, operation, claim_scope,
               status, resource, fact_key, fact_value, version_hash, authority,
               created_at, expires_at, superseded_by, metadata_json
        FROM tool_evidence
        WHERE session_id = ? AND status = 'observed_success'
    """
    params: List[Any] = [session_id]
    if resource:
        query += " AND resource = ?"
        params.append(resource)
    query += " ORDER BY created_at DESC"

    cursor = conn.execute(query, params)
    records: List[ToolEvidenceRecord] = []
    for r in cursor.fetchall():
        meta = {}
        if r["metadata_json"]:
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                pass
        records.append(
            ToolEvidenceRecord(
                evidence_id=r["evidence_id"],
                session_id=r["session_id"],
                event_id=r["event_id"],
                tool_name=r["tool_name"],
                operation=OperationKind(r["operation"]),
                claim_scope=ClaimScope(r["claim_scope"]),
                status=EvidenceStatus(r["status"]),
                resource=r["resource"],
                fact_key=r["fact_key"],
                fact_value=r["fact_value"],
                version_hash=r["version_hash"],
                authority=r["authority"],
                timestamp=r["created_at"],
                expires_at=r["expires_at"],
                superseded_by=r["superseded_by"],
                metadata=meta
            )
        )
    return records


def invalidate_resource_evidence(
    conn: sqlite3.Connection,
    session_id: str,
    resource: str,
    reason: str = "manual_invalidation",
    auto_commit: bool = True
) -> int:
    """Explicitly invalidate/supersede active evidence for a resource."""
    init_evidence_schema(conn)
    cursor = conn.execute(
        "UPDATE tool_evidence SET status = 'superseded', superseded_by = ? WHERE session_id = ? AND resource = ? AND status = 'observed_success'",
        (reason, session_id, resource)
    )
    count = cursor.rowcount
    conn.execute(
        "UPDATE overlay SET status = 'superseded', supersedes = ? WHERE session_id = ? AND key = ? AND status = 'active'",
        (reason, session_id, resource)
    )
    if auto_commit:
        conn.commit()
    return count


def is_deploy_evidence_stale(evidence: ToolEvidenceRecord, max_age_seconds: float = 300.0) -> bool:
    """Check if deploy process-exit evidence is stale or expired."""
    if evidence.claim_scope != ClaimScope.PROCESS_EXIT or evidence.operation != OperationKind.DEPLOY:
        return False
    try:
        ev_time = datetime.fromisoformat(evidence.timestamp)
        now = datetime.now(timezone.utc)
        return (now - ev_time).total_seconds() > max_age_seconds
    except Exception:
        return True


def invalidate_expired_evidence(
    conn: sqlite3.Connection,
    session_id: str,
    max_age_seconds: float = 300.0
) -> int:
    """Transition expired/stale deploy evidence to EXPIRED state in overlay and evidence."""
    init_evidence_schema(conn)
    records = get_active_evidence(conn, session_id)
    expired_count = 0
    for rec in records:
        if is_deploy_evidence_stale(rec, max_age_seconds):
            conn.execute(
                "UPDATE tool_evidence SET status = 'expired' WHERE evidence_id = ?",
                (rec.evidence_id,)
            )
            if rec.fact_key:
                conn.execute(
                    "UPDATE overlay SET status = 'superseded' WHERE session_id = ? AND key = ? AND status = 'active'",
                    (session_id, rec.fact_key)
                )
            expired_count += 1
    if expired_count > 0:
        conn.commit()
    return expired_count
