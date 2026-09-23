"""Cognitive Context Bus coordinating modular runtime execution for Hermes Agent.

Implements the contract-based proposal -> policy -> commit lifecycle.
JIT Context OS is the foundational substrate; cognitive layers act as modular plugins.
"""

import time
import json
import sqlite3
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cognitive.contracts import (
    CognitionConfig,
    CognitionMode,
    TaskState,
    IntuitionProposal,
    MetaGuidance,
    PlanProposal,
    GateDecision,
    RepairTicket,
    ExperienceEvent,
    EpistemicObligation,
    extract_epistemic_obligations
)
import l0.db as l0_db
import l0.overlay as l0_overlay
import context.compiler as context_compiler
from l0.epistemics import (
    evaluate_conscience_gate,
    resolve_required_modalities,
    record_experience_event,
    retrieve_experience_priors
)


class CognitiveBus:
    """Decoupled, modular cognitive context bus."""

    def __init__(self, config: Optional[CognitionConfig] = None, conn: Optional[sqlite3.Connection] = None):
        self.config = config or CognitionConfig()
        self.conn = conn or l0_db.get_db()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

    def initialize_task(self, task_id: str, question: str, attached_files: Optional[List[str]] = None) -> TaskState:
        """Initialize task state and resolve modalities."""
        attached_files = attached_files or []
        mod_info = resolve_required_modalities(question, attached_files)
        session_id = f"cog_{task_id[:12]}"
        l0_overlay.ensure_session(self.conn, session_id)
        
        return TaskState(
            task_id=task_id,
            question=question,
            attached_files=attached_files,
            modalities=mod_info["required_modalities"],
            session_id=session_id,
            status="INITIALIZED",
            created_at=time.time()
        )

    def step_intuition(self, task: TaskState, lfm_extractor_fn=None) -> IntuitionProposal:
        """Execute Subconscious sensory extraction if enabled; otherwise return deterministic fallback."""
        if not self.config.intuition_enabled:
            # Minimal/Standard mode: zero latency direct mapping
            mod_info = resolve_required_modalities(task.question, task.attached_files)
            return IntuitionProposal(
                intent="direct_execution",
                target_entity="unknown",
                output_format="scalar",
                recommended_tools=mod_info["recommended_tools"],
                observations=[],
                hypotheses=[],
                required_modalities=task.modalities,
                duration_ms=0.0
            )

        # Check local experience priors first (Local Intuition Replay)
        priors = retrieve_experience_priors(self.conn, intent=task.question[:60], modalities=task.modalities, limit=2)
        prior_str = [p["strategy"] for p in priors] if priors else []

        if lfm_extractor_fn:
            t0 = time.time()
            raw_data = lfm_extractor_fn(task.question)
            dur_ms = (time.time() - t0) * 1000
            obs = [str(x.get("description", x) if isinstance(x, dict) else x) for x in raw_data.get("observations", [])]
            hyps = [str(x.get("hypothesis", x) if isinstance(x, dict) else x) for x in raw_data.get("hypotheses", [])]
            return IntuitionProposal(
                intent=raw_data.get("intent", "general_inquiry"),
                target_entity=raw_data.get("target_entity", "unknown"),
                output_format=raw_data.get("output_format", "scalar"),
                recommended_tools=raw_data.get("recommended_tools", ["web_search", "python_exec"]),
                observations=obs,
                hypotheses=hyps + prior_str,
                required_modalities=task.modalities,
                duration_ms=dur_ms
            )

        # Rule-based fast path
        return IntuitionProposal(
            intent="task_resolution",
            target_entity="query_target",
            output_format="scalar",
            recommended_tools=["python_exec", "web_search"],
            observations=[],
            hypotheses=prior_str,
            required_modalities=task.modalities,
            duration_ms=0.0
        )

    def should_trigger_meta_guidance(
        self,
        task: TaskState,
        intuition: IntuitionProposal,
        attempt_count: int = 0,
        turn_count: int = 0,
        delta_knowledge: int = 1
    ) -> bool:
        """Determines whether Superconscious MetaGuidance should be invoked.
        Lazy invocation: Only on complex mathematical operators, repair tickets, or when Ego is stalled.
        """
        if not self.config.superconscious_enabled:
            return False
        if not self.config.lazy_meta_guidance:
            return True

        # 1. Complex mathematical operators requiring candidate set management
        oblig = extract_epistemic_obligations(task.question)
        if oblig.candidate_set_required or oblig.operator in ("ARGMIN", "ARGMAX", "SIBLING_EXCLUSION", "EXCLUSIVITY"):
            return True

        # 2. Repair ticket / retry from Conscience
        if attempt_count > 0:
            return True

        # 3. Ego stalled or zero information gain across turns
        if delta_knowledge == 0 and turn_count >= 2:
            return True

        return False

    def step_superconscious(
        self,
        task: TaskState,
        intuition: IntuitionProposal,
        planner_fn=None,
        attempt_count: int = 0,
        turn_count: int = 0,
        delta_knowledge: int = 1
    ) -> MetaGuidance:
        """Execute Superconscious meta-guidance (Lazy on-demand). Authority = 0.0 (Advisory only)."""
        if not self.should_trigger_meta_guidance(task, intuition, attempt_count, turn_count, delta_knowledge):
            # Fast-path: Ego plans and executes directly without top-down anchoring
            return MetaGuidance(
                goal=task.question[:80],
                suggested_paths=["Ego directly executes and investigates with tools."],
                authority=0.0,
                duration_ms=0.0
            )

        if planner_fn:
            t0 = time.time()
            raw_guidance = planner_fn(task.question, intuition.to_dict())
            dur_ms = (time.time() - t0) * 1000
            
            goal = ""
            risks = []
            paths = []
            for line in raw_guidance.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith("goal:"):
                    goal = line[5:].strip()
                elif line.lower().startswith("risks:"):
                    risks.append(line[6:].strip())
                elif line.lower().startswith(("suggested angles:", "angles:", "paths:")):
                    paths.append(line.split(":", 1)[1].strip())
                elif line.startswith(("-", "•", "*")):
                    if risks and not paths:
                        risks.append(line.lstrip("-•* "))
                    else:
                        paths.append(line.lstrip("-•* "))
                elif line[0].isdigit() and "." in line:
                    paths.append(line.split(".", 1)[1].strip())

            return MetaGuidance(
                goal=goal or task.question[:80],
                constraints=intuition.observations,
                risks=risks or ["Anchoring on first candidate", "Premature commitment without full proof"],
                suggested_paths=paths or [raw_guidance],
                authority=0.0,
                duration_ms=dur_ms
            )

        return MetaGuidance(goal=task.question[:80], suggested_paths=["Ego independently explores and evaluates candidates"])

    def step_compile_capsule(self, task: TaskState, intuition: IntuitionProposal, plan: PlanProposal) -> str:
        """Compile JIT Context Capsule via substrate compiler."""
        # 1. Append observations into L0 WAL (Authority = 0.9)
        for obs in intuition.observations:
            l0_overlay.append_event(
                self.conn,
                session_id=task.session_id,
                role="system",
                content=f"Prompt Constraint: {obs}",
                origin="podswiadomosc",
                fact_kind="verified_fact",
                fact_key="observation",
                fact_value=obs
            )

        # 2. Append hypotheses into L0 WAL (Authority = 0.0, non-authoritative)
        for hyp in intuition.hypotheses:
            l0_overlay.append_event(
                self.conn,
                session_id=task.session_id,
                role="system",
                content=f"Hypothesis (Auth 0.0): {hyp}",
                origin="podswiadomosc",
                fact_kind="hypothesis",
                fact_key="hypothesis",
                fact_value=hyp
            )

        # 3. Substrate compilation
        capsule_res = context_compiler.compile_context(self.conn, session_id=task.session_id, user_message=task.question)
        full_capsule = str(capsule_res).rstrip()

        # Wrap with active cognitive bus state
        plan_str = " | ".join(plan.steps)
        obs_str = "; ".join(intuition.observations)
        hyp_str = "; ".join(intuition.hypotheses)
        tools_str = ", ".join(intuition.recommended_tools)

        # Extract mathematical & epistemic obligations from question semantics
        oblig = extract_epistemic_obligations(task.question)
        oblig_block = ""
        if oblig.invariants:
            inv_lines = "\n".join(f"    • {inv}" for inv in oblig.invariants)
            oblig_block = f"\n  [EPISTEMIC OBLIGATION & COMPLETENESS CONTRACT]\n    • Operator: {oblig.operator or 'DIRECT_LOOKUP'}\n    • Candidate Set Required: {oblig.candidate_set_required}\n    • Source Contract: {oblig.source_contract or 'OPEN_WEB'}\n{inv_lines}"

        if "</ONA_CONTEXT>" in full_capsule:
            prefix = full_capsule.replace("</ONA_CONTEXT>", "").rstrip()
            full_capsule = f"""{prefix}
  [COGNITIVE BUS (Mode: {self.config.mode.value})]
    • Intent: {intuition.intent} | Tools: {tools_str}
    • Observations: {obs_str or 'None'}
    • Hypotheses (Auth 0.0): {hyp_str or 'None'}
    • Strategy Plan: {plan_str}{oblig_block}
  [ACTIVE INVARIANTS]
    • ZERO FAKE / EVIDENCE FIRST: Every factual assertion requires physical tool verification.
    • INVARIANT I4: No LLM token can promote a claim without tool proof.
    • HARD CONSTRAINT: End response with exactly 'FINAL ANSWER: <value>'.
</ONA_CONTEXT>"""

        return full_capsule

    def step_conscience_gate(self, task: TaskState, candidate_answer: Optional[str], tool_events: List[Dict[str, Any]]) -> GateDecision:
        """Execute deterministic Conscience Gate (Option D). Conscience never rewrites content."""
        if not self.config.conscience_deterministic:
            # If Conscience is turned off, raw candidate is returned as-is
            return GateDecision(
                decision="UNVERIFIED",
                candidate_answer=str(candidate_answer),
                verified_answer=str(candidate_answer),
                reason="CONSCIENCE_DISABLED"
            )

        decision = evaluate_conscience_gate(
            candidate_answer=str(candidate_answer or ""),
            tool_events=tool_events,
            question=task.question
        )
        return decision

    def step_commit_experience(self, task: TaskState, intuition: IntuitionProposal, plan: PlanProposal, tool_events: List[Dict[str, Any]], gate: GateDecision) -> Optional[str]:
        """Commit verified trajectory to local Experience Buffer."""
        if not gate.is_verified():
            return None

        tools_seq = [t.get("tool", "") for t in tool_events if t.get("tool")]
        ev_refs = [t.get("spill_path", "") for t in tool_events if t.get("spill_path")]
        strategy_str = " -> ".join(plan.steps)

        exp_id = record_experience_event(
            conn=self.conn,
            task_signature=f"{intuition.intent}|{task.modalities}",
            intent=intuition.intent,
            modalities=task.modalities,
            strategy=strategy_str,
            tool_sequence=tools_seq,
            evidence_refs=ev_refs,
            outcome="VERIFIED"
        )
        return exp_id
