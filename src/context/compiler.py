"""Context Compiler combining L0, L1, and L2 layers into an ONA_CONTEXT capsule."""

import sqlite3
from typing import Dict, List, Optional, Set
from context.renderer import render_capsule
from l0.overlay import ensure_session, get_active_overlays
from l0.recent_fence import compute_content_hash, get_missing_recent_turns
from l1.scope import resolve_scope
from l1.project_cache import get_project_context
from l2.triggers import should_trigger_deep_retrieval
from l2.client import query_deep_context

def compile_context(
    conn: sqlite3.Connection,
    session_id: str,
    user_message: str,
    transcript_messages: Optional[List[Dict]] = None,
    conversation_history: Optional[List[Dict]] = None,
    **kwargs
) -> str:
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
    
    # 2. L0 Active Overlays (RYOW - Invariant I2)
    overlays = get_active_overlays(conn, session_id, limit=5)
    current_statements = [o["value"] for o in overlays if o["value"] != user_message]
    
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
    project_doc = get_project_context(active_scope)
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
            
    return render_capsule(
        scope=active_scope,
        epoch=epoch,
        current_statements=current_statements,
        project_summary=project_summary,
        recalled_facts=recalled_facts if recalled_facts else None
    )
