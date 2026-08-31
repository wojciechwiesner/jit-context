"""Scope Resolver with Hysteresis (Invariant I5)."""

import re
from typing import Tuple, List, Optional

EXPLICIT_SCOPE_PATTERNS = [
    r"(?:przejd[zź]my do|pracujemy nad|otw[oó]rz projekt|projekt:?)\s+([a-zA-Z0-9_\-]+)",
    r"(?:prze[lł][aą]cz na|zmie[nń] projekt na)\s+([a-zA-Z0-9_\-]+)"
]

CROSS_PROJECT_QUERY_PATTERNS = [
    r"(?:jak w|w projekcie|z projektu|jak robili[sś]my w)\s+([a-zA-Z0-9_\-]+)",
    r"(?:por[oó]wnaj z|sprawd[zź] w)\s+([a-zA-Z0-9_\-]+)"
]

KNOWN_PROJECTS = {
    "boocco", "invoiceflow", "faktury", "onboarding_flow", "masteros",
    "thesaiver", "lifos", "hermes", "borg", "uniproos", "uniproworks",
    "whatsapp_center", "videosy", "twojastara", "dwa_kroki"
}

def resolve_scope(
    message: str,
    current_active_scope: str,
    pending_candidate_scope: Optional[str] = None,
    candidate_turns_count: int = 0
) -> Tuple[str, List[str], Optional[str], int]:
    """Resolves active_scope and retrieval_scopes with hysteresis.
    
    Returns:
      (active_scope, retrieval_scopes, next_candidate_scope, next_candidate_turns)
    """
    text_lower = message.lower()
    
    # 1. Check explicit command (immediate switch)
    for pat in EXPLICIT_SCOPE_PATTERNS:
        m = re.search(pat, text_lower)
        if m:
            cand = m.group(1).strip()
            if cand in KNOWN_PROJECTS or len(cand) >= 3:
                return cand, [cand], None, 0
                
    # 2. Check cross-project query (adds to retrieval_scopes without switching active_scope - Invariant I5)
    cross_scopes = set()
    for pat in CROSS_PROJECT_QUERY_PATTERNS:
        m = re.search(pat, text_lower)
        if m:
            cand = m.group(1).strip()
            if cand in KNOWN_PROJECTS or len(cand) >= 3:
                cross_scopes.add(cand)
                
    if cross_scopes:
        retrieval = [current_active_scope] + [s for s in sorted(cross_scopes) if s != current_active_scope]
        return current_active_scope, retrieval, None, 0

    # 3. Check sustained candidate mention (requires 2 consecutive turns to switch active_scope)
    detected_candidate = None
    for p in KNOWN_PROJECTS:
        if p in text_lower and p != current_active_scope:
            detected_candidate = p
            break
            
    if detected_candidate:
        if pending_candidate_scope == detected_candidate:
            new_turns = candidate_turns_count + 1
            if new_turns >= 2:
                # Sustained threshold met -> switch active scope
                return detected_candidate, [detected_candidate], None, 0
            else:
                return current_active_scope, [current_active_scope, detected_candidate], detected_candidate, new_turns
        else:
            return current_active_scope, [current_active_scope, detected_candidate], detected_candidate, 1
            
    return current_active_scope, [current_active_scope], None, 0
