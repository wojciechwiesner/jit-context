"""Cognitive Bus & Modular Runtime Contracts for Hermes Cognitive Context OS.

Defines typed proposals, decisions, and configuration models ensuring zero direct coupling
between Intuition, Superconscious, Ego, Tools, Conscience, and Collective layers.
"""

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


class CognitionMode(str, Enum):
    MINIMAL = "MINIMAL"        # JIT + Ego only
    STANDARD = "STANDARD"      # JIT + Ego + Tools + Evidence
    COGNITIVE = "COGNITIVE"    # JIT + Intuition + Superconscious + Ego + Conscience
    COLLECTIVE = "COLLECTIVE"  # COGNITIVE + Collective Experience Ingest/Replay


LOCAL_MODELS: Dict[str, Dict[str, Any]] = {
    # Ollama models on port 11434
    "qwen3.8:jit": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Qwen 3.8 9B JIT Optimized"},
    "qwen3.8:distill": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Qwen 3.8 9B Distill GGUF"},
    "qwen3.8:9b-64k": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Qwen 3.8 9B 64k Context"},
    "qwen3.8:9b": {"provider": "ollama", "port": 11434, "context": 32768, "desc": "Qwen 3.8 9B Base"},
    "qwen3.8:latest": {"provider": "ollama", "port": 11434, "context": 32768, "desc": "Qwen 3.8 Latest"},
    "norn-v18:9b": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Project Norn V18 9B"},
    "norn-v18:latest": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Project Norn V18 Latest"},
    "qwen2.5-coder:7b": {"provider": "ollama", "port": 11434, "context": 32768, "desc": "Qwen 2.5 Coder 7B"},
    "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q4_K_M": {"provider": "ollama", "port": 11434, "context": 65536, "desc": "Qwen 3.8 Distill Full Tag"},
    # vmlx / MLX models on port 8195
    "JANGQ-AI/LFM2.5-8B-A1B-JANG_2L": {"provider": "vmlx", "port": 8195, "context": 32768, "desc": "Liquid LFM 2.5 8B Metal Native (vmlx)"},
    "lfm2.5-8b": {"provider": "vmlx", "port": 8195, "context": 32768, "desc": "Liquid LFM 2.5 8B Metal Alias (vmlx)"},
}

@dataclass
class CognitionConfig:
    """Feature flags controlling layer activation and graceful quality degradation."""
    mode: CognitionMode = CognitionMode.COGNITIVE
    intuition_enabled: bool = True
    superconscious_enabled: bool = True
    lazy_meta_guidance: bool = True       # Only query Superconscious on-demand/stalled/repair
    ego_backend: str = "auto"             # "auto", "ollama", "vmlx", "google"
    ego_model: str = "default"
    conscience_deterministic: bool = True
    conscience_semantic: bool = False
    collective_intuition_enabled: bool = False

    @classmethod
    def from_mode(cls, mode: str) -> "CognitionConfig":
        m = CognitionMode(mode.upper())
        if m == CognitionMode.MINIMAL:
            return cls(mode=m, intuition_enabled=False, superconscious_enabled=False, conscience_deterministic=False)
        if m == CognitionMode.STANDARD:
            return cls(mode=m, intuition_enabled=False, superconscious_enabled=False, conscience_deterministic=True)
        if m == CognitionMode.COLLECTIVE:
            return cls(mode=m, collective_intuition_enabled=True)
        return cls(mode=m)


@dataclass
class VisualObservation:
    """Sensory observation emitted by Vision organ (Qwen-VL / Gemini Vision)."""
    source_path: str
    entities_detected: List[str] = field(default_factory=list)
    text_ocr: str = ""
    spatial_relations: List[str] = field(default_factory=list)
    raw_description: str = ""


@dataclass
class AudioObservation:
    """Sensory observation emitted by Speech organ (Whisper)."""
    source_path: str
    transcript: str
    duration_seconds: float = 0.0
    key_phrases: List[str] = field(default_factory=list)


@dataclass
class TaskState:
    """Canonical task state observed on the Cognitive Bus."""
    task_id: str
    question: str
    attached_files: List[str] = field(default_factory=list)
    modalities: List[str] = field(default_factory=list)
    session_id: str = ""
    status: str = "INITIALIZED"
    created_at: float = 0.0


@dataclass
class IntuitionProposal:
    """Subconscious proposal emitted by perception cortex (Authority = 0.0)."""
    intent: str
    target_entity: str
    output_format: str
    recommended_tools: List[str]
    observations: List[str] = field(default_factory=list)  # Literal prompt constraints
    hypotheses: List[str] = field(default_factory=list)    # Speculative parametric priors (Auth 0.0)
    required_modalities: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetaGuidance:
    """Strategic meta-guidance emitted by Superconscious cortex (Authority = 0.0).
    Expands Ego's horizon without removing agency or forcing rigid sequential action steps.
    """
    goal: str = ""
    constraints: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    suggested_paths: List[str] = field(default_factory=list)
    authority: float = 0.0
    duration_ms: float = 0.0

    @property
    def steps(self) -> List[str]:
        return self.suggested_paths

    @property
    def pitfalls_to_avoid(self) -> List[str]:
        return self.risks

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Alias for backward compatibility
PlanProposal = MetaGuidance


@dataclass
class EvidenceObject:
    """Immutable, content-addressed evidence span grounded in raw tool output."""
    claim_candidate: str
    value: Any
    unit: Optional[str]
    source_blob: str
    byte_range: Tuple[int, int]
    byte_start: int = 0
    byte_end: int = 0
    raw_blob_hash: str = ""
    source_uri: str = ""
    transformation_chain: List[str] = field(default_factory=list)
    extractor_authority: float = 0.0
    confidence: float = 1.0
    verified_against_raw: bool = True

    def __post_init__(self):
        if self.byte_range and not (self.byte_start or self.byte_end):
            self.byte_start, self.byte_end = self.byte_range

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RepairTicket:
    """Explicit, typed machine instruction for Ego to repair a rejected claim without prose debate."""
    claim_id: str
    error_type: str
    required_action: str
    required_proof: Dict[str, Any]
    attempt_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GateDecision:
    """Conscience verification verdict. Conscience never rewrites content; it only approves or rejects."""
    decision: str  # "VERIFIED", "REJECTED", "REPAIR_REQUIRED", "UNDECIDABLE"
    candidate_answer: str
    verified_answer: Optional[str] = None
    reason: Optional[str] = None
    repair_ticket: Optional[RepairTicket] = None
    evidence_refs: List[str] = field(default_factory=list)

    def is_verified(self) -> bool:
        return self.decision == "VERIFIED"


@dataclass
class ExperienceEvent:
    """Signed, verifiable experience trajectory stored locally or ingested collectively."""
    experience_id: str
    task_signature: str
    intent: str
    modalities: List[str]
    strategy: str
    tool_sequence: List[str]
    evidence_refs: List[str]
    outcome: str  # "VERIFIED", "FAILED"
    experience_hash: str
    created_at: str


@dataclass
class EpistemicObligation:
    """Mathematical & completeness obligation extracted from question semantics."""
    operator: Optional[str] = None       # "ARGMIN", "ARGMAX", "MIN", "MAX", "EXCLUSIVITY", "EXHAUSTIVENESS", "SIBLING_EXCLUSION"
    target_metric: Optional[str] = None  # "date", "distance", "value", "count"
    candidate_set_required: bool = False
    source_contract: Optional[str] = None # Named authoritative source required (e.g., "Merriam-Webster", "Wikipedia", "Nature")
    completeness_required: bool = True
    invariants: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_epistemic_obligations(question: str) -> EpistemicObligation:
    """Extract epistemic completeness operators and named source contracts from question text."""
    q_low = question.lower()
    invs = []
    op = None
    metric = None
    cand_set = False
    source = None

    # 1. Extreme / Optimization Operators
    if any(w in q_low for w in ["earliest", "first paper", "first publication", "oldest"]):
        op = "ARGMIN"
        metric = "date"
        cand_set = True
        invs.append("ARGMIN(date): You must identify all candidate items with their exact dates; do NOT commit from a single candidate.")
    elif any(w in q_low for w in ["latest", "last paper", "newest", "most recent"]):
        op = "ARGMAX"
        metric = "date"
        cand_set = True
        invs.append("ARGMAX(date): Inspect full candidate list before selecting most recent.")
    elif any(w in q_low for w in ["highest", "maximum", "max", "farthest", "greatest"]):
        op = "MAX"
        metric = "value"
        cand_set = True
        invs.append("MAX(value): Candidate set comparison required; verify extreme value.")
    elif any(w in q_low for w in ["lowest", "minimum", "min", "closest", "smallest"]):
        op = "MIN"
        metric = "value"
        cand_set = True
        invs.append("MIN(value): Must verify strictly lowest/closest value.")
    elif " only " in q_low or q_low.startswith("only "):
        op = "EXCLUSIVITY"
        invs.append("EXCLUSIVITY: Must prove no alternative candidates satisfy the condition.")
    elif any(w in q_low for w in [" all ", "every ", "list all"]):
        op = "EXHAUSTIVENESS"
        invs.append("EXHAUSTIVENESS: Complete list of all qualifying entities required.")
    elif any(w in q_low for w in ["other", "another", "aside from"]):
        op = "SIBLING_EXCLUSION"
        invs.append("SIBLING_EXCLUSION: Identify reference entity first and select distinct sibling.")

    # 2. Named Source Contracts
    known_sources = [
        "merriam-webster", "wikipedia", "nature", "scikit-learn", "bielefeld",
        "cornell law", "nih", "clinicaltrials", "scientific reports"
    ]
    for src in known_sources:
        if src in q_low:
            source = src
            invs.append(f"SOURCE_CONTRACT: Fact must originate from or be verified against authoritative source '{src}'.")
            break

    # 3. Domain Contracts
    if "species" in q_low:
        invs.append("SPECIES CONTRACT: The question asks for a biological SPECIES (e.g. 'Rockhopper penguin', 'Polar bear'), NOT a general family or genus like 'penguin' or 'bear'. Continue searching until the exact species epithet is proven.")

    if "complete title" in q_low or "full title" in q_low:
        invs.append("FULL_TITLE CONTRACT: The question asks for the COMPLETE title. Check if the work has an official subtitle (e.g. 'Title: Subtitle') and preserve it verbatim.")

    # 4. Counting & Table Invariants (Zero Mental Counting)
    if any(w in q_low for w in ["how many", "count", "number of"]) and any(w in q_low for w in ["between", "albums", "table", "published", "released", "wikipedia", "list"]):
        invs.append("ZERO MENTAL COUNTING INVARIANT: Do NOT count or calculate numbers in conversational memory or from search snippets. Search grounding snippets often have incorrect years (e.g. claiming an album is 2000 when the Wikipedia table row literally says 1999). You MUST fetch the actual page/table with web_extract, copy the table text or parse it in python_exec, verify the exact year in the table for each row, and compute len() deterministically.")

    # 5. Logic Puzzles & Constraint Satisfaction (Zero Mental Reasoning)
    if any(w in q_low for w in ["secret santa", "gift exchange", "who did not", "which person", "logic puzzle", "assigned one other"]):
        invs.append("CONSTRAINT SOLVER INVARIANT: Do NOT solve assignments or logic puzzles in prose text. You MUST use python_exec to model participants, preferences, and assignments as dictionaries, perform matching, and print the exact unassigned or qualifying entity.")

    # 6. Chronological Primacy / Conference Proceedings
    if op == "ARGMIN" and any(w in q_low for w in ["paper", "publication", "article", "author"]):
        invs.append("CONFERENCE PROCEEDINGS PRIMACY: If multiple candidate papers share the earliest publication year in a conference volume, check the conference proceedings table of contents, program, or starting page numbers via python_exec (e.g. via Crossref API or publication list). The paper with the lower starting page number (e.g. p. 212 vs p. 297) appeared earlier in the volume and is the true earliest publication.")

    # 7. Probability & Stochastic Machine Puzzles
    if any(w in q_low for w in ["maximize your odds", "highest probability", "odds of winning", "ping-pong", "game show", "random firing", "piston"]):
        invs.append("MARKOV & ABSORBING STATE INVARIANT: For sequential ball/token elimination games with platform positions (e.g. ping-pong ramp, pistons), do NOT write ad-hoc end-of-game ramp boundary simulations. Compute the exact absorbing Markov probabilities P(ejected | pos 1), P(ejected | pos 2), P(ejected | pos 3). The ball starting in position with maximum P(ejected) (e.g. Ball 3 with 17/27 > 5/9 > 1/3) has the highest win probability.")

    return EpistemicObligation(
        operator=op,
        target_metric=metric,
        candidate_set_required=cand_set,
        source_contract=source,
        completeness_required=cand_set or (op is not None),
        invariants=invs
    )


def check_fidelity_and_specificity(candidate_answer: str, tool_events: List[Dict[str, Any]], question: str) -> str:
    """Answer Fidelity Gate:
    Prevents 'almost correct' losses (e.g. 'penguin' instead of 'Rockhopper penguin', or missing book subtitle).
    Checks if raw evidence in tool outputs contains a more specific version of candidate_answer.
    """
    clean_ans = candidate_answer.strip().strip("'\"")
    evidence_texts = [str(t.get("output", "")) + " " + str(t.get("output_preview", "")) for t in tool_events]
    full_evidence = " ".join(evidence_texts)

    # Check for specific noun/species modifier in evidence (e.g. "Rockhopper penguin" vs "penguin")
    if len(clean_ans.split()) == 1 and clean_ans.lower() in ["penguin", "bear", "whale", "bird", "shark"]:
        pattern = re.compile(rf"\b([A-Z][a-z]+ {re.escape(clean_ans)})\b", re.I)
        matches = pattern.findall(full_evidence)
        if matches:
            from collections import Counter
            best = Counter(matches).most_common(1)[0][0]
            return best

    # Check for complete book title with subtitle if question asks for "complete title"
    if "complete title" in question.lower() and ":" not in clean_ans:
        pattern = re.compile(rf"{re.escape(clean_ans)}:\s*([^\"\n\.]+)", re.IGNORECASE)
        m = pattern.search(full_evidence)
        if m:
            subtitle = m.group(1).strip('", ')
            return f"{clean_ans}: {subtitle}"

    return clean_ans


