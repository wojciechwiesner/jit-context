"""Context Compiler combining L0, L1, and L2 layers into an ONA_CONTEXT capsule."""

import sqlite3
import time
import re
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

def _norm_statement(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _prior_user_statements(overlays: List[Dict], user_message: str) -> List[str]:
    """Prior user statements, excluding the current turn and harness/system notifications.

    The overlay stores the raw user turn, while user_message may be the extracted genuine
    instruction (or vice versa), so exact equality missed the current turn in 34/40 live
    capsules. Containment on normalized text catches both directions.
    """
    try:
        from hooks import extract_genuine_user_instruction, is_synthetic_harness_message
    except ImportError:  # compiler used standalone (benchmarks) without the plugin hooks module
        def extract_genuine_user_instruction(text: str) -> str:
            return text

        def is_synthetic_harness_message(text: str) -> bool:
            return False

    current = _norm_statement(user_message)
    out: List[str] = []
    for o in overlays:
        if o.get("kind") != "statement":
            continue
        value = o.get("value") or ""
        if is_synthetic_harness_message(value):
            continue
        norm = _norm_statement(extract_genuine_user_instruction(value))
        if not norm:
            continue
        if current and (norm == current or norm in current or current in norm):
            continue
        out.append(value)
    return out


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
    current_statements = _prior_user_statements(overlays, user_message)
    verified_facts = [{"key": o.get("key", ""), "value": o.get("value", "")} for o in overlays if o.get("kind") == "verified_fact"]
    
    # 3. L0 RecentTurnFence (Deduplication across compressions)
    transcript_hashes: Set[str] = set()
    if transcript_messages:
        for msg in transcript_messages:
            content = msg.get("content", "")
            if content:
                transcript_hashes.add(compute_content_hash(content))
                
    missing_turns = get_missing_recent_turns(conn, session_id, transcript_hashes)
    fence_prior = _prior_user_statements(
        [{"kind": "statement", "value": t["content"]} for t in missing_turns], user_message
    )
    for content in fence_prior:
        if content not in current_statements:
            current_statements.append(content)
            
    # 4. L1 Project Context (GSD STATE.md & Architecture integration)
    session_cwd = session.get("last_cwd") or kwargs.get("session_cwd")
    project_doc = get_project_context(active_scope, session_cwd=session_cwd)
    project_summary = None
    if project_doc:
        # Strip redundant sections that duplicate active invariants or are empty profiler watermarks
        cleaned_doc = re.sub(
            r"## Safety Invariants & Engineering Rules.*?(?=\n##|\Z)",
            "",
            project_doc,
            flags=re.DOTALL
        )
        cleaned_doc = re.sub(r"\n- \*\*Environment Profiles\*\*:\s*\n", "\n", cleaned_doc)
        cleaned_doc = re.sub(r"---\s*\n\*Generated by Hermes JIT Context OS Profiler.*?\*", "", cleaned_doc)
        cleaned_doc = re.sub(r"\n{3,}", "\n\n", cleaned_doc).strip()

        # Calibrated budget: up to ~4,500 chars (~1,100–1,200 tokens) to ensure complete certainty
        # Preserves full Architecture, Engine, Key Files & Modules, and Active State
        trimmed = cleaned_doc
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
    cwd_obj = Path(session_cwd) if session_cwd and Path(session_cwd).exists() else Path.cwd()

    for o in overlays:
        k = o.get("key", "")
        if k.startswith("read:") or k.startswith("file:") or k.startswith("write:"):
            p = k.split(":", 1)[1]
            if p and p not in existing_paths:
                existing_paths.add(p)
                v = o.get("value", "")
                
                # Extract High-Density AST Pointer / Symbol Map
                symbols = []
                f_lines_count = 0
                snippet = None
                try:
                    f_path = cwd_obj / p if not Path(p).is_absolute() else Path(p)
                    if f_path.exists() and f_path.is_file():
                        raw_content = f_path.read_text(encoding="utf-8", errors="ignore")
                        all_lines = raw_content.splitlines()
                        f_lines_count = len(all_lines)
                        
                        # Python AST Symbol extraction
                        if p.endswith(".py"):
                            import ast
                            try:
                                tree = ast.parse(raw_content)
                                for node in tree.body:
                                    if isinstance(node, ast.ClassDef):
                                        methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                                        m_str = f"methods: {', '.join(methods[:6])}" if methods else "class"
                                        symbols.append(f"class {node.name} ({m_str}, L{node.lineno})")
                                    elif isinstance(node, ast.FunctionDef):
                                        symbols.append(f"def {node.name}() L{node.lineno}")
                            except Exception:
                                pass
                                
                        # Fallback regex / line scan for non-python or unparseable files
                        if not symbols:
                            for idx, l in enumerate(all_lines[:40], 1):
                                l_str = l.strip()
                                if l_str.startswith(("def ", "class ", "export ", "async def ", "function ")):
                                    symbols.append(f"{l_str.split('(')[0]} L{idx}")
                                    if len(symbols) >= 6:
                                        break
                                        
                        # Active short snippet (either full file if <= 60 lines or top signatures)
                        if f_lines_count <= 60:
                            snippet = raw_content.strip()
                        elif symbols:
                            snippet = "\n".join([f"- {s}" for s in symbols[:8]])
                        else:
                            snippet = "\n".join(all_lines[:20])
                except Exception:
                    pass

                working_set.append({
                    "path": p,
                    "summary": f"{f_lines_count} lines" if f_lines_count else (v if v and v != "read_ok" else "active module"),
                    "snippet": snippet,
                    "pointer": f"@ref:{p}"
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

    # Codebase Map discovery across all standard project layouts (app/, src/, lib/)
    if not dev_runtime.get("codebase_map") and session_cwd:
        try:
            cwd_p = Path(session_cwd)
            found_files = []
            patterns = (
                "app/**/*.py", "src/**/*.py", "lib/**/*.py",
                "app/**/*.ts", "src/**/*.ts", "lib/**/*.ts",
                "app/**/*.js", "src/**/*.js", "lib/**/*.js",
                "tests/**/*.py", "tests/**/*.ts", "tests/**/*.js",
            )
            for pattern in patterns:
                for fp in cwd_p.glob(pattern):
                    if fp.is_file() and not fp.name.startswith("__") and not fp.name.startswith("."):
                        found_files.append(str(fp.relative_to(cwd_p)))
                        if len(found_files) >= 16:
                            break
                if len(found_files) >= 16:
                    break
            if found_files:
                dev_runtime["codebase_map"] = found_files
        except Exception:
            pass

    # Active Invariants (max 4)
    active_invariants = list(kwargs.get("active_invariants") or [])

    # Automated Cascade Contract Invariants based on user intent & domain keywords
    combined_signal = f"{user_message} {' '.join(current_statements[-3:])}".lower()

    # Context-aware regex matching to eliminate false-positive substring collisions
    # 1. Auth Graph: require auth/credentials keywords, or session when bound to auth/token/user context
    # Strip URLs and LLM token terminology to avoid false positive triggers on Observatory links or benchmark token stats
    clean_signal = re.sub(r"https?://\S+", "", combined_signal)
    clean_signal = re.sub(r"\b(token[ówy]|tokens? count|token budget|llm tokens?|prompt tokens?)\b", "", clean_signal)

    is_auth_intent = bool(re.search(r"\b(auth\w*|login\w*|wylog\w*|zalog\w*|oauth\w*|jwt|sso|access_token|refresh_token|bearer|ciasteczk\w*|cookies?)\b", clean_signal))
    if not is_auth_intent and re.search(r"\b(sesj[aeiouy]\w*|sessions?)\b", clean_signal):
        is_auth_intent = bool(re.search(r"\b(użytkownik\w*|user\w*|hasł\w*|password\w*|login\w*|wylog\w*|auth\w*|uprawnien\w*|tożsamoś\w*)\b", clean_signal))
    if is_auth_intent:
        active_invariants.append(
            "CASCADE INVARIANT (Auth Graph): Token/cookie changes require verifying all issuers (login, refresh, OAuth/SSO, session endpoints) and client session handlers."
        )

    # 2. Tenant Scope
    if re.search(r"\b(tenant|company|firma|scoping|rls|wielofirm)\b", combined_signal):
        active_invariants.append(
            "CASCADE INVARIANT (Tenant Scope): Endpoints must scope DB access by company_id and return 404 (not 403) on cross-tenant requests."
        )

    # 3. Schema Cascade: require explicit database/migration/schema terms (NOT bare 'model' which matches ML/decision models)
    if re.search(r"\b(migracj[aei]|migrations?|alembic|bazy danych|kolumn[yae]|database schema|db schema)\b", combined_signal):
        active_invariants.append(
            "CASCADE INVARIANT (Schema Cascade): DB model mutations require corresponding migration files and API schema synchronization."
        )

    # 4. Compute Invariant: deterministic calculation
    if re.search(r"\b(oblicz|calculate|permutacj[ae]|collatz|matematyk|symulacj[ae]|obliczeniow|trapped|levenshtein)\b", combined_signal):
        active_invariants.append(
            "COMPUTE INVARIANT (Tool-First Epistemics): Execute deterministic multi-step math/simulations via interpreter tools instead of manual simulation in thought tokens."
        )

    # 5. Agentic Coding: require actual code refactoring/modification intent
    if re.search(r"\b(refactor|implement[uj]?|napisz kod|zmień kod|patchuj|napraw bug|endpoint|pull request)\b", combined_signal):
        active_invariants.append(
            "AGENTIC CODING INVARIANT: LoB locality > excessive abstraction, SRP <300 lines, surgical patch over full rewrites, Bit-fals runtime proof required."
        )

    if session_cwd and len(active_invariants) < 4:
        try:
            cwd_p = Path(session_cwd)
            state_file = cwd_p / ".planning" / "STATE.md"
            if state_file.exists():
                for line in state_file.read_text(encoding="utf-8").splitlines():
                    if any(w in line for w in ("Invariant", "Inwariant", "ZAKAZ", "CANON", "MANDATORY")):
                        clean_inv = line.strip().lstrip("-*# ").strip()
                        if clean_inv and len(clean_inv) < 200 and clean_inv not in active_invariants:
                            active_invariants.append(clean_inv)
                            if len(active_invariants) >= 4:
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

    # Domain & Tool Source Routing (Resolves WhatsApp, Sessions/Observatory, Media/VLM, Decision Trees)
    try:
        from context.domain_router import resolve_domain_routing
        routing = resolve_domain_routing(user_message, session_cwd=session_cwd)
        for src in routing.get("domain_sources", []):
            if src not in available_pointers:
                available_pointers.append(src)
        for hint in routing.get("action_hints", []):
            h_text = f"@hint: {hint}"
            if h_text not in available_pointers:
                available_pointers.append(h_text)
    except Exception:
        pass

    # JEV Asynchronous Prefetch & Hybrid Fact Reranking (Slot 2 + Slot 5)
    try:
        from cognitive.jev_engine import get_jev_scorer
        jev = get_jev_scorer()
        if recalled_facts:
            candidates = [{"key": f"fact_{i}", "value": f} for i, f in enumerate(recalled_facts)]
            jev.prefetch_async(user_message, candidates)
            reranked = jev.rerank_hybrid(user_message, candidates)
            recalled_facts = [r["value"] for r in reranked]
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
        "budget": distill_result.get("budget", 10000)
    })
