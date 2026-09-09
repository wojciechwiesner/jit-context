"""Cascade Context Distiller for Hermes JIT Context OS v0.2.

Three-tier pipeline:
1. LLM Semantic Classifier (Tag & Identify):
   - Identifies [KEEP_CRITICAL] (errors, test failures, user intent, file paths, ports)
   - Identifies [SAFE_TO_COLLAPSE] (terminal download progress bars, ASCII blocks, hash manifests)
   - Identifies [IRRELEVANT_PROJECT] (stale project contexts)
2. Verbatim Deterministic Cleaner:
   - Strips ONLY [SAFE_TO_COLLAPSE] blocks
   - Preserves [KEEP_CRITICAL] content 100% verbatim (exact characters/syntax)
   - Preserves error indicators and uses neutral omission markers
3. Elastic Assembler & Confidence Arbiter:
   - Dynamically scales capsule size (800 tok for direct fixes up to 3,500 tok for complex refactors)
   - Evaluates confidence score [0.00-1.00]
   - Escapes all serialized XML attributes and contents
   - Enforces classifier containment (no scope override, no summary as direct user)
"""

import os
import re
import json
import time
import math
import requests
from typing import Dict, Any, List, Optional, Tuple, Set

from context.renderer import escape_xml_attr, escape_xml_content

ALLOWED_COMPLEXITY: Set[str] = {"status", "direct_fix", "feature", "refactoring"}


def get_google_api_key() -> Optional[str]:
    # Check ~/.hermes/.env
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("GOOGLE_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return os.environ.get("GOOGLE_API_KEY")


def fast_deterministic_prefilter(raw_text: str) -> str:
    """
    Instantly collapses repetitive download bars and terminal noise without altering code.
    Replaces fabricated progress-success wording with neutral omission markers and preserves errors.
    """
    if not raw_text:
        return ""

    error_pattern = re.compile(
        r'\b(error|fatal|fail|failed|failure|incomplete|exception|panic|abort|aborted)\b',
        re.IGNORECASE
    )

    lines = raw_text.splitlines()
    processed_lines: List[str] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Check docker pull / layer pull patterns
        if re.match(r'^\s*(?:pulling manifest|pulling [a-f0-9]+:)', line):
            error_lines = []
            while i < n and re.match(r'^\s*(?:pulling manifest|pulling [a-f0-9]+:)', lines[i]):
                if error_pattern.search(lines[i]):
                    error_lines.append(lines[i])
                i += 1
            processed_lines.append('[omitted: layer pull progress]')
            if error_lines:
                processed_lines.extend(error_lines)
            continue

        # Check sha256 verifying patterns
        if re.match(r'^\s*verifying sha256 digest', line):
            error_lines = []
            while i < n and re.match(r'^\s*verifying sha256 digest', lines[i]):
                if error_pattern.search(lines[i]):
                    error_lines.append(lines[i])
                i += 1
            processed_lines.append('[omitted: sha256 digest verification]')
            if error_lines:
                processed_lines.extend(error_lines)
            continue

        # Check block characters █{5,}
        if re.search(r'█{5,}', line):
            if error_pattern.search(line):
                # Preserve the error portion, only replace block characters
                subbed = re.sub(r'█{5,}\s*', '[omitted: progress bar] ', line)
                processed_lines.append(subbed.strip())
            else:
                processed_lines.append('[omitted: progress bar]')
            i += 1
            continue

        processed_lines.append(line)
        i += 1

    # Collapse consecutive identical omission markers
    deduped_lines: List[str] = []
    for pline in processed_lines:
        if pline.startswith('[omitted:') and deduped_lines and deduped_lines[-1] == pline:
            continue
        deduped_lines.append(pline)

    return "\n".join(deduped_lines).strip()


CLASSIFIER_PROMPT = """You are the Semantic Tagger, Prompt Enhancer & Cascade Impact Analyzer for Hermes JIT Context OS.
Analyze the provided noisy session text and classify components:
1. Extract verbatim CRITICAL text (user instructions, exact error messages, file paths, ports, exports).
2. Determine active scope/project name.
3. Compute a confidence score (0.00 to 1.00) indicating if the project context and user goal are unambiguous.
4. Estimate task complexity ('direct_fix', 'status', 'feature', 'refactoring').
5. PROMPT ENHANCER:
   - enhanced_technical_spec: Translate terse user instructions into a precise, concrete engineering specification grounded in the codebase and error state.
   - acceptance_criteria: Exact observable verification condition (e.g. 'pytest tests/... passes with exit code 0').
   - target_files: List of primary files to inspect or modify (use real codebase paths if provided in Codebase Map, do not invent fictitious paths).
6. CASCADING CONTRACT ANALYSIS:
   - cascading_impacts: List all sibling files, dependent routes, callers, or auth/schema providers that share this contract and MUST be inspected or updated to prevent broken invariants (e.g. when changing session cookies/tokens, check all token issuers, SSO endpoints, and client session handlers).

Respond ONLY with valid JSON matching:
{
  "active_scope": "project-name",
  "confidence": 0.95,
  "complexity": "refactoring",
  "critical_elements": ["exact file path or error or export rule", ...],
  "safe_summary_of_user_intent": "one-line summary of goal",
  "background_process_note": "one-line status of background task if any",
  "enhanced_technical_spec": "precise technical specification",
  "acceptance_criteria": "exact verification command and condition",
  "target_files": ["path/to/file.py"],
  "cascading_impacts": ["Contract impact description: sibling files to verify", ...]
}
"""


def validate_classifier_output(
    data: Any,
    raw_source_text: str,
    trusted_scope: str = "general"
) -> Optional[Dict[str, Any]]:
    """
    Validate classifier schema, enum values, and finite confidence range.
    Reject malformed/NaN/out-of-source values.
    Enforce classifier containment: cannot override active_scope or label summary as direct user.
    Require critical fragments to be exact source spans.
    """
    if not isinstance(data, dict):
        return None

    # Confidence validation: finite float in [0.0, 1.0], not boolean
    raw_conf = data.get("confidence")
    if raw_conf is None or isinstance(raw_conf, bool) or not isinstance(raw_conf, (int, float)):
        return None
    conf = float(raw_conf)
    if not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
        return None

    # Complexity validation: must match allowed enum
    complexity = data.get("complexity")
    if not isinstance(complexity, str) or complexity not in ALLOWED_COMPLEXITY:
        return None

    # Critical elements validation: list of strings that MUST be exact source spans
    raw_elements = data.get("critical_elements")
    valid_elements: List[str] = []
    if isinstance(raw_elements, list):
        for elem in raw_elements:
            if isinstance(elem, str):
                elem_clean = elem.strip()
                # Exact source span requirement
                if elem_clean and elem_clean in raw_source_text:
                    valid_elements.append(elem_clean)
                # Out-of-source values are strictly rejected

    # Active scope containment: classifier CANNOT override trusted active_scope
    # Any scope proposed by classifier is ignored in favor of trusted_scope
    resolved_scope = trusted_scope

    # Safe summary and background note validation (strings only)
    safe_summary = data.get("safe_summary_of_user_intent")
    if safe_summary is not None and not isinstance(safe_summary, str):
        return None
    summary_str = str(safe_summary).strip() if safe_summary else ""

    bg_note = data.get("background_process_note")
    if bg_note is not None and not isinstance(bg_note, str):
        return None
    bg_str = str(bg_note).strip() if bg_note else ""

    # Prompt Enhancer validation
    enhanced_spec = data.get("enhanced_technical_spec")
    spec_str = str(enhanced_spec).strip()[:400] if enhanced_spec and isinstance(enhanced_spec, str) else None

    criteria = data.get("acceptance_criteria")
    crit_str = str(criteria).strip()[:300] if criteria and isinstance(criteria, str) else None

    raw_targets = data.get("target_files")
    target_files = []
    if isinstance(raw_targets, list):
        for t in raw_targets:
            if isinstance(t, str) and t.strip():
                target_files.append(t.strip()[:150])

    raw_impacts = data.get("cascading_impacts")
    cascading_impacts = []
    if isinstance(raw_impacts, list):
        for imp in raw_impacts:
            if isinstance(imp, str) and imp.strip():
                cascading_impacts.append(imp.strip()[:200])

    return {
        "active_scope": resolved_scope,
        "confidence": conf,
        "complexity": complexity,
        "critical_elements": valid_elements,
        "safe_summary_of_user_intent": summary_str,
        "background_process_note": bg_str,
        "enhanced_technical_spec": spec_str,
        "acceptance_criteria": crit_str,
        "target_files": target_files if target_files else None,
        "cascading_impacts": cascading_impacts if cascading_impacts else None
    }


def call_llm_classifier(
    raw_text: str,
    timeout: float = 6.0,
    trusted_scope: str = "general"
) -> Optional[Dict[str, Any]]:
    """Calls Gemini Flash using direct GOOGLE_API_KEY with local Ollama fallback, strictly validated."""
    prefiltered = fast_deterministic_prefilter(raw_text[:6000])

    # Tier 1: Cloud SOTA via Google Gemini Flash
    key = get_google_api_key()
    if key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{CLASSIFIER_PROMPT}\n\nINPUT TO CLASSIFY:\n{prefiltered}"}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 2000,
                "thinkingConfig": {
                    "thinkingBudget": 0
                }
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                content = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
                cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
                parsed = json.loads(cleaned)
                return validate_classifier_output(parsed, raw_source_text=raw_text, trusted_scope=trusted_scope)
        except Exception:
            pass

    # Tier 2: Local Offline Fallback via Ollama (qwen2.5-coder:7b)
    try:
        ollama_payload = {
            "model": "qwen2.5-coder:7b",
            "prompt": f"{CLASSIFIER_PROMPT}\n\nINPUT TO CLASSIFY:\n{prefiltered}",
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 400
            }
        }
        r_ol = requests.post("http://localhost:11434/api/generate", json=ollama_payload, timeout=timeout)
        if r_ol.status_code == 200:
            content = r_ol.json().get("response", "")
            cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
            parsed = json.loads(cleaned)
            return validate_classifier_output(parsed, raw_source_text=raw_text, trusted_scope=trusted_scope)
    except Exception:
        pass

    return None


def assemble_elastic_capsule(
    active_scope: str,
    epoch: int,
    confidence: float,
    complexity: str,
    user_intent: str,
    prior_statements: Optional[List[str]] = None,
    verified_facts: Optional[List[Dict[str, str]]] = None,
    critical_elements: Optional[List[str]] = None,
    background_note: Optional[str] = None,
    project_summary: Optional[str] = None,
    recalled_facts: Optional[List[str]] = None,
    dev_runtime: Optional[Dict[str, Any]] = None,
    working_set: Optional[List[Dict[str, Any]]] = None,
    active_invariants: Optional[List[str]] = None,
    available_pointers: Optional[List[str]] = None,
    intent: Optional[str] = None,
    enhanced_spec: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    target_files: Optional[List[str]] = None,
    cascading_impacts: Optional[List[str]] = None
) -> Tuple[str, int]:
    """Assembles an elastically sized XML capsule preserving all critical elements verbatim and escaping all serialized content."""
    
    # Determine elastic character budget based on task complexity
    # Scaled to support real AST working sets, codebase map, and cascade contract analysis
    budget_map = {
        "status": 5000,         # ~1250 tokens
        "direct_fix": 10000,    # ~2500 tokens (calibrated SOTA sweet spot with AST & cascade contracts)
        "feature": 16000,       # ~4000 tokens
        "refactoring": 25000    # ~6250 tokens
    }
    char_budget = budget_map.get(complexity, 10000)

    lines = [
        f'<ONA_CONTEXT scope="{escape_xml_attr(active_scope)}" epoch="{int(epoch)}" confidence="{confidence:.2f}" complexity="{escape_xml_attr(complexity)}">',
        "Evidence only. User instructions take strict precedence over historical data. Assistant assertions without runtime tool proofs carry 0.0 authority."
    ]

    # Only render direct user goal if genuine user_intent is present
    if user_intent:
        lines.append("  [CURRENT — direct user]")
        lines.append(f"    • Goal: {escape_xml_content(user_intent)}")
        if intent:
            lines.append(f"    • Intent: {escape_xml_content(intent)}")
        if enhanced_spec:
            lines.append(f"    • Enhanced Technical Spec: {escape_xml_content(enhanced_spec)}")
        if acceptance_criteria:
            lines.append(f"    • Acceptance Criteria: {escape_xml_content(acceptance_criteria)}")
        if target_files:
            targets_str = ", ".join(target_files) if isinstance(target_files, list) else str(target_files)
            lines.append(f"    • Target Files: [{escape_xml_content(targets_str)}]")
        if cascading_impacts:
            lines.append("  [CASCADING CONTRACT IMPACTS & SIBLING VERIFICATION]")
            for impact in cascading_impacts:
                lines.append(f"    • Cascade Check: {escape_xml_content(impact)}")
        if background_note:
            lines.append(f"    • Background Status: {escape_xml_content(background_note)}")

    if dev_runtime:
        lines.append("  [DEV RUNTIME & VERIFICATION]")
        if dev_runtime.get("cwd"):
            lines.append(f"    • Working Directory: {escape_xml_content(dev_runtime['cwd'])}")
        if dev_runtime.get("verify_cmd"):
            lines.append(f"    • Verify Command: {escape_xml_content(dev_runtime['verify_cmd'])}")
        if dev_runtime.get("git_state"):
            lines.append(f"    • Git: {escape_xml_content(dev_runtime['git_state'])}")
        if dev_runtime.get("allowed_tools"):
            tools_val = dev_runtime["allowed_tools"]
            tools_str = ", ".join(tools_val) if isinstance(tools_val, list) else str(tools_val)
            lines.append(f"    • Allowed Tools: [{escape_xml_content(tools_str)}]")
        if dev_runtime.get("codebase_map"):
            cmap = dev_runtime["codebase_map"]
            cmap_str = ", ".join(cmap) if isinstance(cmap, list) else str(cmap)
            lines.append(f"    • Codebase Map: [{escape_xml_content(cmap_str)}]")

    if working_set:
        lines.append("  [WORKING SET & CONTRACTS]")
        for item in working_set:
            path = item.get("path", "")
            desc = item.get("summary") or item.get("signature") or item.get("status", "active")
            ptr = item.get("pointer", f"@ref:{path}")
            snippet = item.get("snippet")
            if snippet:
                lines.append(f"    • {ptr} ({escape_xml_content(desc)}):")
                for s_line in str(snippet).splitlines()[:50]:
                    lines.append(f"        {escape_xml_content(s_line)}")
            else:
                lines.append(f"    • {ptr} ({escape_xml_content(desc)})")

    if verified_facts:
        lines.append("  [VERIFIED RUNTIME PROOFS (Authority 1.0)]")
        for vf in verified_facts:
            k = escape_xml_content(vf.get("key", ""))
            v = escape_xml_content(vf.get("value", ""))
            lines.append(f"    • [{k}] {v}")

    if active_invariants:
        lines.append("  [ACTIVE INVARIANTS]")
        for inv in active_invariants:
            lines.append(f"    • {escape_xml_content(inv.strip())}")

    if available_pointers:
        lines.append("  [AVAILABLE POINTERS]")
        for ptr in available_pointers:
            lines.append(f"    • {escape_xml_content(ptr.strip())}")

    if prior_statements:
        lines.append("  [PRIOR USER INSTRUCTIONS]")
        for stmt in prior_statements:
            clean_stmt = stmt.strip().split("\n")[0][:250]
            lines.append(f"    • {escape_xml_content(clean_stmt)}")

    if recalled_facts:
        lines.append("  [RECALLED KNOWLEDGE (Advisory 0.5)]")
        for rf in recalled_facts:
            lines.append(f"    • {escape_xml_content(rf.strip())}")

    if critical_elements:
        lines.append("  [VERBATIM CRITICAL CONTRACTS]")
        for elem in critical_elements:
            lines.append(f"    • {escape_xml_content(elem.strip())}")

    if project_summary:
        lines.append("  [PROJECT CONTEXT]")
        # Trim project summary to fit within elastic budget
        current_len = sum(len(l) for l in lines)
        remaining = max(500, char_budget - current_len - 100)
        trimmed_proj = project_summary.strip()
        if len(trimmed_proj) > remaining:
            trimmed_proj = trimmed_proj[:remaining] + "\n    [...truncated to elastic budget]"
        lines.append(f"    {escape_xml_content(trimmed_proj)}")

    lines.append("</ONA_CONTEXT>")
    capsule = "\n".join(lines)
    
    # Hard budget assertion/truncation
    if len(capsule) > char_budget:
        overflow = len(capsule) - char_budget
        # Truncate inside capsule before closing tag
        truncated_body = capsule[:char_budget - 25] + "\n[...budget cap]\n</ONA_CONTEXT>"
        capsule = truncated_body

    return capsule, char_budget


def distill_context_cascade(
    raw_statements: List[str],
    active_scope: str,
    epoch: int,
    prior_statements: Optional[List[str]] = None,
    verified_facts: Optional[List[Dict[str, str]]] = None,
    project_summary: Optional[str] = None,
    recalled_facts: Optional[List[str]] = None,
    dev_runtime: Optional[Dict[str, Any]] = None,
    working_set: Optional[List[Dict[str, Any]]] = None,
    active_invariants: Optional[List[str]] = None,
    available_pointers: Optional[List[str]] = None,
    intent: Optional[str] = None
) -> Dict[str, Any]:
    """Complete 3-tier cascade distillation entrypoint."""
    start_time = time.time()
    raw_combined = "\n".join(raw_statements)
    latest_user_intent = raw_statements[-1] if raw_statements else ""
    priors = prior_statements if prior_statements is not None else (raw_statements[:-1] if len(raw_statements) > 1 else [])

    # Infer epistemic intent if not explicitly passed
    if not intent and latest_user_intent:
        u_low = latest_user_intent.lower()
        if re.search(r"\b(błąd|bug|fail|error|nie działa|napraw|popraw|crash|wyjątek|exception|fix)\b", u_low):
            intent = "BUG_REPORT"
        elif re.search(r"\b(dodaj|stwórz|zrób|zaimplementuj|feature|nowy|utwórz|create|implement)\b", u_low):
            intent = "FEATURE_SPEC"
        elif re.search(r"\b(wdrożyć|deploy|uruchom|odpal|start|stop|restart|build)\b", u_low):
            intent = "COMMAND"
        elif re.search(r"\b(jak|dlaczego|czy|gdzie|jaki|co to|analiza|sprawdź|explain|how|why)\b", u_low):
            intent = "QUERY"
        else:
            intent = "DIRECT_TASK"

    # Scope containment: active_scope cannot be overridden by classifier
    resolved_scope = active_scope

    # Fast check: if input is already clean and short (< 1500 chars), bypass LLM
    if len(raw_combined) < 1500 and "████" not in raw_combined:
        # Fast path: user_intent is strictly latest_user_intent (direct user)
        # Fast deterministic prompt enhancement
        d_targets = [str(w.get("path")) for w in working_set if isinstance(w, dict) and w.get("path")] if working_set else []
        cmap = dev_runtime.get("codebase_map") if dev_runtime else []
        if cmap and isinstance(cmap, list):
            for cf in cmap:
                bname = str(cf).split("/")[-1]
                if (bname.lower() in latest_user_intent.lower() or str(cf).lower() in latest_user_intent.lower()) and str(cf) not in d_targets:
                    d_targets.append(str(cf))
        d_targets = d_targets if d_targets else None
        d_crit = f"{dev_runtime.get('verify_cmd', 'pytest')} passes with exit code 0" if dev_runtime and dev_runtime.get('verify_cmd') else None
        d_spec = f"Execute '{latest_user_intent}' focusing on {', '.join(d_targets[:3])}." if d_targets else None

        capsule, budget = assemble_elastic_capsule(
            active_scope=resolved_scope,
            epoch=epoch,
            confidence=1.00,
            complexity="feature" if working_set else "direct_fix",
            user_intent=latest_user_intent,
            prior_statements=priors,
            verified_facts=verified_facts,
            critical_elements=[],
            project_summary=project_summary,
            recalled_facts=recalled_facts,
            dev_runtime=dev_runtime,
            working_set=working_set,
            active_invariants=active_invariants,
            available_pointers=available_pointers,
            intent=intent,
            enhanced_spec=d_spec,
            acceptance_criteria=d_crit,
            target_files=d_targets
        )
        return {
            "capsule": capsule,
            "distilled": False,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "confidence": 1.00,
            "complexity": "feature" if working_set else "direct_fix",
            "budget": budget
        }

    # Step 1: LLM Classifier
    llm_meta = call_llm_classifier(raw_combined, trusted_scope=resolved_scope)

    if not llm_meta:
        # Fallback to deterministic cleaner if LLM offline / timeout / rejected
        cleaned_statements = [fast_deterministic_prefilter(s) for s in raw_statements if s.strip()]
        user_intent = cleaned_statements[-1] if cleaned_statements else latest_user_intent
        clean_priors = cleaned_statements[:-1] if len(cleaned_statements) > 1 else priors
        
        fb_targets = [str(w.get("path")) for w in working_set if isinstance(w, dict) and w.get("path")] if working_set else None
        fb_crit = f"{dev_runtime.get('verify_cmd', 'pytest')} passes with exit code 0" if dev_runtime and dev_runtime.get('verify_cmd') else None
        fb_spec = f"Execute '{user_intent}' focusing on {', '.join(fb_targets[:3])}." if fb_targets else None

        capsule, budget = assemble_elastic_capsule(
            active_scope=resolved_scope,
            epoch=epoch,
            confidence=0.85,
            complexity="feature",
            user_intent=user_intent,
            prior_statements=clean_priors,
            verified_facts=verified_facts,
            critical_elements=[],
            project_summary=project_summary,
            recalled_facts=recalled_facts,
            dev_runtime=dev_runtime,
            working_set=working_set,
            active_invariants=active_invariants,
            available_pointers=available_pointers,
            intent=intent,
            enhanced_spec=fb_spec,
            acceptance_criteria=fb_crit,
            target_files=fb_targets
        )
        return {
            "capsule": capsule,
            "distilled": False,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "confidence": 0.85,
            "complexity": "feature",
            "budget": budget
        }

    # Step 2 & 3: Verbatim Assembler with elastic budget
    # Classifier CANNOT override active_scope (resolved_scope remains active_scope)
    confidence = float(llm_meta.get("confidence", 0.95))
    complexity = llm_meta.get("complexity", "feature")

    # Invariant I1 & Provenance Containment:
    # Classifier summary CANNOT be labeled as direct user! Only latest_user_intent enters user_intent.
    user_intent = latest_user_intent
    
    # Critical elements: only exact source spans from raw_combined
    raw_critical = llm_meta.get("critical_elements", [])
    critical_elements = [
        elem for elem in raw_critical
        if isinstance(elem, str) and elem.strip() and elem.strip() in raw_combined
    ]
    bg_note = llm_meta.get("background_process_note")
    llm_spec = llm_meta.get("enhanced_technical_spec")
    llm_crit = llm_meta.get("acceptance_criteria")
    llm_targets = llm_meta.get("target_files")
    llm_cascade = llm_meta.get("cascading_impacts")

    capsule, budget = assemble_elastic_capsule(
        active_scope=resolved_scope,
        epoch=epoch,
        confidence=confidence,
        complexity=complexity,
        user_intent=user_intent,
        prior_statements=priors,
        verified_facts=verified_facts,
        critical_elements=critical_elements,
        background_note=bg_note if bg_note and bg_note != user_intent else None,
        project_summary=project_summary,
        recalled_facts=recalled_facts,
        dev_runtime=dev_runtime,
        working_set=working_set,
        active_invariants=active_invariants,
        available_pointers=available_pointers,
        intent=intent,
        enhanced_spec=llm_spec,
        acceptance_criteria=llm_crit,
        target_files=llm_targets,
        cascading_impacts=llm_cascade
    )

    return {
        "capsule": capsule,
        "distilled": True,
        "duration_ms": round((time.time() - start_time) * 1000, 2),
        "confidence": confidence,
        "complexity": complexity,
        "budget": budget,
        "requires_clarification": confidence < 0.85
    }
