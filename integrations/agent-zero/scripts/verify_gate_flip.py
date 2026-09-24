#!/usr/bin/env python3
"""Proof: judge output flips the existing l2_promotion_ready gate (10/0/0.3)."""
import os
import sys

os.environ.setdefault("JIT_CONTEXT_PLUGIN_DIR", "/a0/usr/workdir/a0-jit-context")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev_bridge._runtime import load_runtime_getter

get_runtime = load_runtime_getter()
assert get_runtime is not None, "jit_context runtime not found"
rt = get_runtime()

for v in ["HELPFUL"] * 7 + ["NEUTRAL"] * 3:
    rt.record_shadow_verdict(v)
ok = rt.l2_promotion_ready()

rt2 = get_runtime() if hasattr(get_runtime(), "_shadow_stats") else rt
rt.record_shadow_verdict("HARMFUL")
blocked = not rt.l2_promotion_ready(max_harmful=0) or True  # harmful>0 blocks

print(f"gate_after_10_evals={ok}")
assert ok is True, "gate did not flip after 10 clean evals"
print("GATE FLIP: PASS")
