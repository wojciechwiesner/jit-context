"""Cascade Context Distiller for Hermes JIT Context OS v0.2.

Three-tier pipeline:
1. LLM Semantic Classifier (Tag & Identify):
   - Identifies [KEEP_CRITICAL] (errors, test failures, user intent, file paths, ports)
   - Identifies [SAFE_TO_COLLAPSE] (terminal download progress bars, ASCII blocks, hash manifests)
   - Identifies [IRRELEVANT_PROJECT] (stale project contexts)
2. Verbatim Deterministic Cleaner:
   - Strips ONLY [SAFE_TO_COLLAPSE] blocks
   - Preserves [KEEP_CRITICAL] content 100% verbatim (exact characters/syntax)
3. Elastic Assembler & Confidence Arbiter:
   - Dynamically scales capsule size (800 tok for direct fixes up to 3,500 tok for complex refactors)
   - Evaluates confidence score [0.00-1.00]
   - If confidence < 0.85, flags requires_clarification=True
"""

import os
import re
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple

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
    """Instantly collapses repetitive download bars and terminal noise without altering code."""
    # Collapse repetitive terminal download progress bars
    text = re.sub(r'(?:pulling manifest|pulling [a-f0-9]+:.*?\n)+', '[Progress: layers pulled successfully]\n', raw_text)
    # Collapse block characters
    text = re.sub(r'█{5,}.*?(?=\n|$)', '[Progress: download complete]', text)
    # Collapse repetitive verifying sha256
    text = re.sub(r'(?:verifying sha256 digest.*?\n)+', '[Progress: sha256 verified]\n', text)
    return text.strip()

CLASSIFIER_PROMPT = """You are the Semantic Tagger for Hermes JIT Context OS.
Analyze the provided noisy session text and classify components:
1. Extract verbatim CRITICAL text (user instructions, exact error messages, file paths, ports, exports).
2. Determine active scope/project name.
3. Compute a confidence score (0.00 to 1.00) indicating if the project context and user goal are unambiguous.
4. Estimate task complexity ('direct_fix', 'status', 'feature', 'refactoring').

Respond ONLY with valid JSON matching:
{
  "active_scope": "project-name",
  "confidence": 0.95,
  "complexity": "refactoring",
  "critical_elements": ["exact file path or error or export rule", ...],
  "safe_summary_of_user_intent": "one-line summary of goal",
  "background_process_note": "one-line status of background task if any"
}
"""

def call_llm_classifier(raw_text: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Calls Gemini Flash using direct GOOGLE_API_KEY with local Ollama fallback."""
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
                return json.loads(cleaned)
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
            return json.loads(cleaned)
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
    project_summary: Optional[str] = None
) -> Tuple[str, int]:
    """Assembles an elastically sized XML capsule preserving all critical elements verbatim."""
    
    # Determine elastic character budget based on task complexity
    budget_map = {
        "status": 3000,         # ~750 tokens
        "direct_fix": 4500,     # ~1100 tokens
        "feature": 8000,        # ~2000 tokens
        "refactoring": 14000    # ~3500 tokens
    }
    char_budget = budget_map.get(complexity, 6000)

    lines = [
        f'<ONA_CONTEXT scope="{active_scope}" epoch="{epoch}" confidence="{confidence:.2f}" complexity="{complexity}">',
        "Evidence only. User instructions take strict precedence over historical data. Assistant assertions without runtime tool proofs carry 0.0 authority."
    ]

    lines.append("  [CURRENT — direct user]")
    lines.append(f"    • Goal: {user_intent}")
    if background_note:
        lines.append(f"    • Background Status: {background_note}")

    if prior_statements:
        lines.append("  [PRIOR USER INSTRUCTIONS]")
        for stmt in prior_statements:
            clean_stmt = stmt.strip().split("\n")[0][:250]
            lines.append(f"    • {clean_stmt}")

    if verified_facts:
        lines.append("  [VERIFIED RUNTIME PROOFS (Authority 1.0)]")
        for vf in verified_facts:
            k = vf.get("key", "")
            v = vf.get("value", "")
            lines.append(f"    • [{k}] {v}")

    if critical_elements:
        lines.append("  [VERBATIM CRITICAL CONTRACTS]")
        for elem in critical_elements:
            lines.append(f"    • {elem.strip()}")

    if project_summary:
        lines.append("  [PROJECT CONTEXT]")
        # Trim project summary to fit within elastic budget
        current_len = sum(len(l) for l in lines)
        remaining = max(1000, char_budget - current_len - 100)
        trimmed_proj = project_summary.strip()
        if len(trimmed_proj) > remaining:
            trimmed_proj = trimmed_proj[:remaining] + "\n    [...truncated to elastic budget]"
        lines.append(f"    {trimmed_proj}")

    lines.append("</ONA_CONTEXT>")
    capsule = "\n".join(lines)
    return capsule, char_budget

def distill_context_cascade(
    raw_statements: List[str],
    active_scope: str,
    epoch: int,
    prior_statements: Optional[List[str]] = None,
    verified_facts: Optional[List[Dict[str, str]]] = None,
    project_summary: Optional[str] = None
) -> Dict[str, Any]:
    """Complete 3-tier cascade distillation entrypoint."""
    start_time = time.time()
    raw_combined = "\n".join(raw_statements)
    latest_user_intent = raw_statements[-1] if raw_statements else ""
    priors = prior_statements if prior_statements is not None else (raw_statements[:-1] if len(raw_statements) > 1 else [])

    # Fast check: if input is already clean and short (< 1500 chars), bypass LLM
    if len(raw_combined) < 1500 and "████" not in raw_combined:
        # Fast path
        capsule, budget = assemble_elastic_capsule(
            active_scope=active_scope,
            epoch=epoch,
            confidence=1.00,
            complexity="direct_fix",
            user_intent=latest_user_intent,
            prior_statements=priors,
            verified_facts=verified_facts,
            critical_elements=[],
            project_summary=project_summary
        )
        return {
            "capsule": capsule,
            "distilled": False,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "confidence": 1.00,
            "budget": budget
        }

    # Step 1: LLM Classifier
    llm_meta = call_llm_classifier(raw_combined)

    if not llm_meta:
        # Fallback to deterministic cleaner if LLM offline / timeout
        cleaned_statements = [fast_deterministic_prefilter(s) for s in raw_statements if s.strip()]
        user_intent = cleaned_statements[-1] if cleaned_statements else latest_user_intent
        clean_priors = cleaned_statements[:-1] if len(cleaned_statements) > 1 else priors
        capsule, budget = assemble_elastic_capsule(
            active_scope=active_scope,
            epoch=epoch,
            confidence=0.85,
            complexity="feature",
            user_intent=user_intent,
            prior_statements=clean_priors,
            verified_facts=verified_facts,
            critical_elements=[],
            project_summary=project_summary
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
    resolved_scope = llm_meta.get("active_scope") or active_scope
    confidence = float(llm_meta.get("confidence", 0.95))
    complexity = llm_meta.get("complexity", "feature")
    # Invariant I1: Direct user statement wins over LLM summary
    user_intent = latest_user_intent or llm_meta.get("safe_summary_of_user_intent", "")
    critical_elements = llm_meta.get("critical_elements", [])
    bg_note = llm_meta.get("background_process_note") or llm_meta.get("safe_summary_of_user_intent")

    capsule, budget = assemble_elastic_capsule(
        active_scope=resolved_scope,
        epoch=epoch,
        confidence=confidence,
        complexity=complexity,
        user_intent=user_intent,
        prior_statements=priors,
        verified_facts=verified_facts,
        critical_elements=critical_elements,
        background_note=bg_note if bg_note != user_intent else None,
        project_summary=project_summary
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
