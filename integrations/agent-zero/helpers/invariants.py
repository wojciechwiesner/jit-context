"""
Epistemic Invariants Engine (I1-I10) for JIT-Context.

Formal invariants protecting autonomous agent context from hallucination amplification,
confidence laundering, prompt injection, and catastrophic memory corruption.
"""

from typing import Dict, Any, List, Optional, Tuple
import re


class EpistemicInvariantError(Exception):
    """Raised when an epistemic invariant is violated."""
    pass


class InvariantChecker:
    @staticmethod
    def sanitize_user_input(text: str) -> str:
        """
        I1 (Direct User Input Wins):
        Ensures direct user input is cleanly formatted and preserved with priority weight 1.0.
        """
        return text.strip() if text else ""

    @staticmethod
    def tag_assistant_output(content: str) -> Dict[str, Any]:
        """
        I3 (Assistant Output Cannot Create Root Facts):
        Assistant outputs receive epistemic weight 0.0 to prevent self-poisoning loops.
        """
        return {
            "content": content,
            "epistemic_weight": 0.0,
            "authority": 0.0,
            "is_root_fact": False,
            "source": "assistant_output"
        }

    @staticmethod
    def tag_external_content(content: str, source_type: str = "web") -> Dict[str, Any]:
        """
        I8 (Quoted Content Quarantine):
        Untrusted external content (web snippets, logs, READMEs) is flagged as quarantined
        to prevent prompt injection attacks.
        """
        return {
            "content": content,
            "epistemic_weight": 0.4,
            "authority": 0.3,
            "is_quarantined": True,
            "source_type": source_type
        }

    @staticmethod
    def check_destructive_auth(operation: str, authorized_by_user: bool) -> bool:
        """
        I9 (Memory Cannot Authorize Destructive Operations):
        Stored memory can provide historical evidence or context, but NEVER authorization
        for destructive actions (e.g. deleting files, DB drops). Explicit user permission required.
        """
        destructive_keywords = ["delete", "drop", "rm -rf", "purge", "format", "unlink"]
        is_destructive = any(k in operation.lower() for k in destructive_keywords)
        if is_destructive and not authorized_by_user:
            raise EpistemicInvariantError(
                f"[I9 Violation] Stored memory cannot authorize destructive operation '{operation}'. "
                "Explicit user prompt confirmation required."
            )
        return True

    @staticmethod
    def check_patch_artifact_precedence(patch_text: str) -> Tuple[bool, str]:
        """
        I10 (Patch Artifact Precedence):
        When an explicit, verified patch artifact exists in context, it takes precedence
        over re-implementing or guessing code modifications from scratch.
        """
        if not patch_text or not patch_text.strip():
            return False, "Empty patch artifact"
        if "diff --git" not in patch_text and "@@" not in patch_text:
            return False, "Invalid patch artifact format: missing git diff/hunk headers"
        return True, "Valid patch artifact"
