"""Context Compiler combining L0, L1, and L2 layers into an ONA_CONTEXT capsule."""

import sqlite3
import time
from typing import List, Dict, Optional, Set, Any, Tuple
from context.renderer import render_capsule
from l0.overlay import ensure_session, get_active_overlays
from l0.recent_fence import compute_content_hash, get_missing_recent_turns
from l1.scope import resolve_scope
from l1.project_cache import get_project_context
from l2.triggers import should_trigger_deep_retrieval
from l2.client import query_deep_context
from context.cascade_distiller import distill_context_cascade

class CapsuleResult(str):
    """String subclass allowing tuple unpacking for backward compatibility."""
    meta: Dict[str, Any]

    def __new__(cls, text: str, meta: Optional[Dict[str, Any]] = None):
        obj = super().__new__(cls, text)
        obj.meta = meta or {}
        return obj

    def __iter__(self):  # type: ignore[override]
        return iter((str(self), self.meta))

def compile_context(
    conn: sqlite3.Connection,
    session_id: str,
    user_message: str,
    transcript_messages: Optional[List[Dict]] = None,
    conversation_history: Optional[List[Dict]] = None,
    **kwargs
) -> CapsuleResult:
    messages = transcript_messages or conversation_history or []
    """Compiles the 3-tier cascade into a single <ONA_CONTEXT> capsule."""
    session = ensure_session(conn, session_id)
    current_scope = session["active_scope"]
    epoch = session["scope_epoch"]
    
    # 1. L1 Scope Resolution (with Hysteresis - Invariant I5)
    active_scope, retrieval_scopes, next_cand, next_turns = resolve_scope(
        user_message,
        current_scope
    )
    if active_scope != current_scope:
        epoch += 1
        conn.execute(
            """
            UPDATE sessions
            SET active_scope = ?, scope_epoch = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (active_scope, epoch, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), session_id)
        )
        conn.commit()
    
    # 2. L0 Active Overlays (RYOW - Invariant I2)
    overlays = get_active_overlays(conn, session_id, limit=10)
    current_statements = [o["value"] for o in overlays if o.get("kind") == "statement" and o["value"] != user_message]
    verified_facts = [{"key": o.get("key", ""), "value": o.get("value", "")} for o in overlays if o.get("kind") == "verified_fact"]
    
    # 3. L0 RecentTurnFence (Deduplication across compressions)
    transcript_hashes: Set[str] = set()
    if transcript_messages:
        for msg in transcript_messages:
            content = msg.get("content", "")
            if content:
                transcript_hashes.add(compute_content_hash(content))
                
    missing_turns = get_missing_recent_turns(conn, session_id, transcript_hashes)
    for t in missing_turns:
        if t["content"] not in current_statements:
            current_statements.append(t["content"])
            
    # 4. L1 Project Context (GSD STATE.md & Architecture integration)
    session_cwd = session.get("last_cwd") or kwargs.get("session_cwd")
    project_doc = get_project_context(active_scope, session_cwd=session_cwd)
    project_summary = None
    if project_doc:
        # Calibrated budget: up to ~4,500 chars (~1,100–1,200 tokens) to ensure complete certainty
        # Preserves full Architecture, Engine, Key Files & Modules, and Active State
        trimmed = project_doc.strip()
        MAX_PROJECT_CHARS = 4500
        if len(trimmed) <= MAX_PROJECT_CHARS:
            project_summary = trimmed
        else:
            project_summary = trimmed[:MAX_PROJECT_CHARS] + "\n[...truncated to JIT budget]"
        
    # 5. L2 Deep Path Trigger (Invariant I6)
    recalled_facts = []
    should_deep, deep_reason = should_trigger_deep_retrieval(user_message)
    if should_deep:
        deep_res = query_deep_context(user_message, retrieval_scopes, conn)
        if deep_res:
            recalled_facts.append(deep_res)

    # 6. Extract SOTA Working Set, Dev Runtime, Invariants and Pointers
    from pathlib import Path
    
    # Working Set from kwargs and L0 tool observations/mutations
    working_set = list(kwargs.get("working_set") or [])
    existing_paths = {w.get("path") for w in working_set if isinstance(w, dict)}
    for o in overlays:
        k = o.get("key", "")
        if k.startswith("read:") or k.startswith("file:") or k.startswith("write:"):
            p = k.split(":", 1)[1]
            if p and p not in existing_paths:
                existing_paths.add(p)
                v = o.get("value", "")
                working_set.append({
                    "path": p,
                    "summary": v if v and v != "read_ok" else "active module"
                })

    # Dev Runtime Baseline
    dev_runtime = dict(kwargs.get("dev_runtime") or {})
    if not dev_runtime.get("cwd") and session_cwd:
        dev_runtime["cwd"] = str(session_cwd)
    if not dev_runtime.get("verify_cmd") and session_cwd:
        try:
            cwd_p = Path(session_cwd)
            if (cwd_p / "pytest.ini").exists() or (cwd_p / "tests").exists() or (cwd_p / "pyproject.toml").exists():
                dev_runtime["verify_cmd"] = "pytest"
            elif (cwd_p / "package.json").exists():
                dev_runtime["verify_cmd"] = "npm test"
            elif (cwd_p / "Cargo.toml").exists():
                dev_runtime["verify_cmd"] = "cargo test"
        except Exception:
            pass
    if not dev_runtime.get("allowed_tools") and kwargs.get("allowed_tools"):
        dev_runtime["allowed_tools"] = kwargs.get("allowed_tools")

    # Active Invariants (max 3)
    active_invariants = list(kwargs.get("active_invariants") or [])
    if not active_invariants and session_cwd:
        try:
            cwd_p = Path(session_cwd)
            state_file = cwd_p / ".planning" / "STATE.md"
            if state_file.exists():
                for line in state_file.read_text(encoding="utf-8").splitlines():
                    if any(w in line for w in ("Invariant", "Inwariant", "ZAKAZ", "CANON", "MANDATORY")):
                        clean_inv = line.strip().lstrip("-*# ").strip()
                        if clean_inv and len(clean_inv) < 200:
                            active_invariants.append(clean_inv)
                            if len(active_invariants) >= 3:
                                break
        except Exception:
            pass

    # Available Pointers
    available_pointers = list(kwargs.get("available_pointers") or [])
    if not available_pointers and session_cwd:
        try:
            cwd_p = Path(session_cwd)
            if (cwd_p / "docs" / "SPECYFIKACJA.md").exists():
                available_pointers.append("Specification: docs/SPECYFIKACJA.md")
            if (cwd_p / ".planning" / "STATE.md").exists():
                available_pointers.append("Active State: .planning/STATE.md")
        except Exception:
            pass

    # 7. Cascade Distillation (LLM Semantic Classifier -> Verbatim Cleaner -> Elastic Assembler)
    raw_statements = current_statements + [user_message]
    distill_result = distill_context_cascade(
        raw_statements=raw_statements,
        active_scope=active_scope,
        epoch=epoch,
        prior_statements=current_statements,
        verified_facts=verified_facts,
        project_summary=project_summary,
        recalled_facts=recalled_facts,
        dev_runtime=dev_runtime if dev_runtime else None,
        working_set=working_set if working_set else None,
        active_invariants=active_invariants if active_invariants else None,
        available_pointers=available_pointers if available_pointers else None,
        intent=kwargs.get("intent")
    )
    
    capsule = distill_result["capsule"]
    confidence = distill_result.get("confidence", 1.0)
    complexity = distill_result.get("complexity", "direct_fix")
    
    # Active Clarification Gate: If confidence < 0.85, inject mandatory clarification directive
    if distill_result.get("requires_clarification", False) or confidence < 0.85:
        clarification_directive = (
            f"\n<CLARIFICATION_REQUIRED>\n"
            f"  Pewność co do kontekstu wynosi {confidence:.2f} (< 0.85). Występuje niejednoznaczność celu lub projektu.\n"
            f"  ZAKAZ wykonywania nieodwracalnych zmian i spekulatywnego kodu.\n"
            f"  Zadaj 1-2 krótkie, precyzyjne pytania doprecyzowujące do użytkownika przed rozpoczęciem pracy.\n"
            f"</CLARIFICATION_REQUIRED>\n"
        )
        capsule += clarification_directive

    return CapsuleResult(capsule, {
        "confidence": confidence,
        "complexity": complexity,
        "distilled": distill_result.get("distilled", False),
        "duration_ms": distill_result.get("duration_ms", 0.0),
        "budget": distill_result.get("budget", 6000)
    })
