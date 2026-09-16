"""Deterministic trigger detection for L2 Deep Path."""

import re
from typing import Tuple, Optional

HISTORY_TRIGGERS = [
    r"\b(?:wcze[sś]niej|ostatnio|kiedy[sś]|kiedy ustalili[sś]my|dlaczego zmienili[sś]my)\b",
    r"\b(?:pami[eę]tasz|poprzednio|jaka by[lł]a decyzja|historia|historycznie)\b"
]

EXPLICIT_MEMORY_TRIGGERS = [
    r"\b(?:sprawd[zź] pami[eę][cć]|przeszukaj pami[eę][cć]|sprawd[zź] obsidiana|w vaulcie|z notatek)\b",
    r"\b(?:co pami[eę]tasz o|co mamy zapisane o)\b"
]

CROSS_PROJECT_TRIGGERS = [
    r"\b(?:jak w|z projektu|jak robili[sś]my w|por[oó]wnaj z)\s+([a-zA-Z0-9_\-]+)\b"
]

LEGAL_COMPLIANCE_TRIGGERS = [
    r"\b(?:art\.?|artyku[łl]|paragraf|§|ustaw[ayie]|kodeks|pke|rodo|gdpr|retencj[ai]|compliance|zgodno[sś][cć] prawna|regulamin|prawo telekomunikacyjne|tajemnica telekomunikacyjna)\b",
    r"\b(?:ksef|faktur[ay] vat|faktur[ay] ksef|vat|jpk|white[- ]?list|bia[łl]a lista|split[- ]?payment)\b"
]

def should_trigger_deep_retrieval(message: str) -> Tuple[bool, Optional[str]]:
    """Returns (should_trigger, reason)."""
    text_lower = message.lower()
    
    for pat in LEGAL_COMPLIANCE_TRIGGERS:
        if re.search(pat, text_lower):
            return True, "legal_compliance_contract"
            
    for pat in EXPLICIT_MEMORY_TRIGGERS:
        if re.search(pat, text_lower):
            return True, "explicit_memory_query"
            
    for pat in HISTORY_TRIGGERS:
        if re.search(pat, text_lower):
            return True, "historical_decision_lookup"
            
    for pat in CROSS_PROJECT_TRIGGERS:
        if re.search(pat, text_lower):
            return True, "cross_project_reference"
            
    return False, None
