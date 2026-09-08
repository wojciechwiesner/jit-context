"""Epistemic Invariants implementation (Invariant I3, I4, I8, I10)."""

def get_authority_for_role(origin: str, role: str) -> float:
    """Invariant I3: Assistant authority is always 0.0 (anti-self-poisoning).
    Direct user authority is 1.0.
    """
    if role == "assistant" or origin == "assistant":
        return 0.0
    if origin == "direct_user":
        return 1.0
    if origin in ("harness_event", "synthetic", "synthetic_demo"):
        return 0.2
    if role == "user" and origin != "external":
        return 0.9 if origin != "direct_user" else 1.0
    if origin in ("runtime_tool_verified", "tool_verified"):
        return 1.0
    if origin in ("tool", "tool_observation"):
        return 0.9
    if origin == "system" and role == "system":
        return 1.0
    if origin == "system":
        return 0.5
    if origin == "external":
        return 0.2
    return 0.0

def cap_derived_authority(root_authority: float, claimed_authority: float) -> float:
    """Invariant I4: Derived authority can never exceed root authority (No authority laundering)."""
    return min(root_authority, claimed_authority)
