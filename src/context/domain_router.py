"""Domain & Tool Source Router for Hermes JIT Context OS.

Deterministically routes user intents to physical data sources, endpoints,
and specialized tools, eliminating blind filesystem exploration.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class DomainRoute:
    def __init__(
        self,
        domain: str,
        sources: List[str],
        recommended_tools: List[str],
        action_hints: List[str],
    ) -> None:
        self.domain = domain
        self.sources = sources
        self.recommended_tools = recommended_tools
        self.action_hints = action_hints


def resolve_domain_routing(query: str, session_cwd: Optional[str] = None) -> Dict[str, Any]:
    """Inspects query text and runtime state to produce domain-specific sources and tool pointers."""
    if not query:
        return {
            "domain_sources": [],
            "recommended_tools": [],
            "action_hints": [],
            "detected_domains": [],
        }

    q_low = query.lower()
    sources: List[str] = []
    tools: List[str] = []
    hints: List[str] = []
    domains: List[str] = []

    # 1. WhatsApp / Contacts / Communication
    if re.search(r"\b(whatsapp|rozmow[ayie]|czat|dominik|udriver|kontakt)\b", q_low):
        domains.append("whatsapp")
        wa_vault_path = Path.home() / "Documents/Wojciech/whatsapp"
        sources.append(
            f"@source:whatsapp: WhatsApp Command Center (API: Suprawhat, Vault: {wa_vault_path})"
        )
        tools.extend(["terminal:curl_wa", "read_file"])
        hints.append(
            "WhatsApp messages: query Suprawhat API with WA_CENTER_API_KEY or check ~/Documents/Wojciech/whatsapp/ directly."
        )

    # 2. Session History / Observatory / Meta-Context
    if re.search(
        r"(\b(sesj[aeiouy\w]*|sessions?|ostatni[aąe]|histori[ia]|observatory|obserwatorium|state\.db|kapsu[lł][aeiy\w]*|capsule)\b|8765|live\?session=|\b202\d{5}_\d{6}\w*\b)",
        q_low,
    ):
        # Exclude pure auth/cookie sessions
        if not re.search(r"\b(jwt|cookie|oauth|ciasteczk|refresh_token)\b", q_low):
            domains.append("session_meta")
            sources.append("@endpoint:observatory: http://127.0.0.1:8765/api/context/live?session={id}")
            sources.append("@source:state_db: ~/.hermes/state.db (SQLite messages, tool_calls, sessions)")
            sources.append("@source:session_overlay: ~/.hermes/state/ona-context/session_overlay.db")
            sources.append("@ref:src/telemetry/observatory.py: Observatory UI and session telemetry API (:8765)")
            sources.append("@ref:src/context/compiler.py: JIT Capsule Compiler and invariant routing")
            tools.extend(["session_search", "terminal:sqlite3", "read_file"])
            hints.append(
                "Hermes Session & Capsule inspection: query Observatory (:8765/api/context/live?session=...) or inspect ~/.hermes/state.db messages."
            )

    # 3. Video / Media / OCR / VLM
    if re.search(r"\b(wideo|video|klatk[ia]|screenshot[y]?|zrzut[y]?|ekran[u]?|ramk[ia]|ocr)\b", q_low):
        domains.append("multimedia")
        tools.extend(["vision_analyze", "video_analyze", "terminal:ffmpeg"])
        hints.append(
            "Video/Image Analysis: extract frames using `ffmpeg -i file.mp4 -vf fps=1 /tmp/frames/frame_%03d.jpg` then call `vision_analyze`."
        )

    # 4. Probabilistic Decision Engine / JEV / Decision Trees
    if re.search(r"\b(drzew[oa]|decision tree|jev|prawdopodobieństw|probabilistyczn)\b", q_low):
        domains.append("decision_engine")
        sources.append("@engine:jev_decision: JEV Alpha Decisions API (~typesafe/jev-latest / OpenRouter /api/alpha/decisions)")
        sources.append("@engine:decision_tree: Probabilistic Decision Trees (/Projects/active/decision-tree-engine)")
        tools.extend(["terminal:python", "write_file", "patch"])
        hints.append(
            "Decision Engine: use probabilistic tree / JEV decisions API instead of blocking LLM token generation."
        )

    return {
        "domain_sources": sources,
        "recommended_tools": sorted(list(set(tools))),
        "action_hints": hints,
        "detected_domains": domains,
    }
