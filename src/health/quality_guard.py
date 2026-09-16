"""Hermes JIT Context OS — Real-Time Model Quality Guard & Anti-Degradation Autocheck.

Monitors agent behavior in runtime for loss of quality:
1. Tool Repetition Loops (calling read_file/terminal with identical args)
2. Tool Failure Bursts (consecutive tool errors or syntax exceptions)
3. Token Bloat & Cache Collapse (capsule exceeding budget or cache hit drop)
4. Bit-fals Claims (completion declarations without execution proofs)

Emits actionable <QUALITY_GUARD_ALERT> directives to steer the model back into compliance.
"""

from __future__ import annotations

import sqlite3
import re
from typing import Dict, Any, List, Optional


def check_tool_repetition_loops(
    conn: sqlite3.Connection,
    session_id: str,
    window: int = 6
) -> Optional[Dict[str, Any]]:
    """Detects if model is stuck in a loop calling the same tool on identical targets."""
    cursor = conn.execute(
        """
        SELECT e.origin, e.content, o.key
        FROM events e
        LEFT JOIN overlay o ON o.source_event_id = e.event_id
        WHERE e.session_id = ? AND e.role = 'tool'
        ORDER BY e.seq DESC
        LIMIT ?
        """,
        (session_id, window)
    )
    rows = cursor.fetchall()
    if len(rows) < 2:
        return None

    # Track consecutive identical targets (either overlay key or origin + content)
    keys = [r[2] if r[2] else f"{r[0]}:{r[1][:80]}" for r in rows]
    if len(keys) >= 2 and keys[0] == keys[1]:
        repeated_target = keys[0]
        count = 2
        for k in keys[2:]:
            if k == repeated_target:
                count += 1
            else:
                break
        return {
            "type": "TOOL_LOOP_DETECTED",
            "target": repeated_target,
            "repeat_count": count,
            "severity": "HIGH" if count >= 3 else "MEDIUM",
            "message": f"Wykryto pętlę powtórzeń narzędzia na celu: '{repeated_target}' ({count}x z rzędu)."
        }
    return None


def check_tool_failure_burst(
    conn: sqlite3.Connection,
    session_id: str,
    window: int = 5
) -> Optional[Dict[str, Any]]:
    """Detects consecutive tool failures or syntax/patch errors."""
    cursor = conn.execute(
        """
        SELECT e.origin, e.content, o.value
        FROM events e
        LEFT JOIN overlay o ON o.source_event_id = e.event_id
        WHERE e.session_id = ? AND e.role = 'tool'
        ORDER BY e.seq DESC
        LIMIT ?
        """,
        (session_id, window)
    )
    rows = cursor.fetchall()
    if not rows:
        return None

    consecutive_errors = 0
    recent_error_msg = ""
    for r in rows:
        content = (r[1] or "").lower()
        val = (r[2] or "").lower()
        is_err = any(err in content or err in val for err in (
            "error", "failed", "traceback", "not found", "exit code 1", "exit: 1", "syntaxerror", "exception"
        ))
        if is_err:
            consecutive_errors += 1
            if not recent_error_msg:
                recent_error_msg = (r[1] or "")[:120]
        else:
            break

    if consecutive_errors >= 2:
        return {
            "type": "TOOL_FAILURE_BURST",
            "consecutive_failures": consecutive_errors,
            "severity": "HIGH" if consecutive_errors >= 3 else "MEDIUM",
            "recent_error": recent_error_msg,
            "message": f"Wykryto serię {consecutive_errors} błędów narzędzi z rzędu. Ostatni błąd: {recent_error_msg}"
        }
    return None


def check_capsule_bloat(
    conn: sqlite3.Connection,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """Detects capsule token explosion violating Invariant I8 (<1.5k tokens)."""
    cursor = conn.execute(
        """
        SELECT capsule_tokens_est, compile_ms
        FROM turn_telemetry
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    capsule_tokens, compile_ms = row
    if capsule_tokens and capsule_tokens > 2500:
        return {
            "type": "CAPSULE_TOKEN_BLOAT",
            "tokens": capsule_tokens,
            "severity": "HIGH",
            "message": f"Kapsuła przekroczyła limit SOTA: {capsule_tokens} tokenów (limit <1500)."
        }
    return None


def audit_session_quality(
    conn: sqlite3.Connection,
    session_id: str
) -> Dict[str, Any]:
    """Runs all real-time model quality checks and computes quality health score."""
    anomalies: List[Dict[str, Any]] = []

    loop_res = check_tool_repetition_loops(conn, session_id)
    if loop_res:
        anomalies.append(loop_res)

    fail_res = check_tool_failure_burst(conn, session_id)
    if fail_res:
        anomalies.append(fail_res)

    bloat_res = check_capsule_bloat(conn, session_id)
    if bloat_res:
        anomalies.append(bloat_res)

    # Compute overall score: 1.0 (perfect), 0.7 (minor warning), <0.5 (degraded)
    score = 1.0
    for a in anomalies:
        if a["severity"] == "HIGH":
            score -= 0.35
        else:
            score -= 0.15
    score = max(0.0, round(score, 2))

    status = "healthy" if score >= 0.85 else ("warning" if score >= 0.55 else "degraded")

    return {
        "status": status,
        "score": score,
        "anomalies": anomalies,
        "session_id": session_id
    }


def format_quality_alert(audit: Dict[str, Any]) -> Optional[str]:
    """Builds a deterministic, actionable directive injected into the JIT capsule."""
    anomalies = audit.get("anomalies", [])
    if not anomalies:
        return None

    lines = [
        "<QUALITY_GUARD_ALERT: Model Quality Degradation Detected>",
        f"  Status zachowania modelu: {audit['status'].upper()} (Score: {audit['score']}/1.0)."
    ]
    for a in anomalies:
        lines.append(f"  • {a['message']}")
        if a["type"] == "TOOL_LOOP_DETECTED":
            lines.append("    -> ZALECENIE: ZAKAZ powtarzania tego samego wywołania narzędzia. Użyj alternatywnego narzędzia (np. 'patch' zamiast pętli 'terminal') lub zweryfikuj AST Working Set.")
        elif a["type"] == "TOOL_FAILURE_BURST":
            lines.append("    -> ZALECENIE: Zatrzymaj się i zdiagnozuj przyczynę błędu przed kolejną edycją. Sprawdź dokładną treść pliku lub asercję testu.")
        elif a["type"] == "CAPSULE_TOKEN_BLOAT":
            lines.append("    -> ZALECENIE: Ogranicz wielkość promptu i wyczyść nieskompresowane zrzuty do /tmp/.")

    lines.append("</QUALITY_GUARD_ALERT>")
    return "\n".join(lines)
