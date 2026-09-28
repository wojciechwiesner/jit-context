#!/usr/bin/env python3
"""A/B: same OpenCode task, same repo, same model -- with plugin vs --pure (no plugins).

Metrics come from `opencode run --format json` events (real runtime, no estimates).
"""
import json
import os
import subprocess
import sys
import time

REPO = os.path.expanduser("~/.hermes/cache/scratch/ab-shopapi")
OPENCODE = os.path.expanduser("~/.opencode/bin/opencode")
PROMPT = (
    "Where is the payment webhook handled in this repo, what is the current blocker, "
    "and which env var must hold the webhook secret? Answer in 3 short lines: FILE=..., BLOCKER=..., ENV=..."
)
EXPECT = {"file": "payments_events.py", "env": "PAYWALL_WH_SECRET"}


def run(variant: str, rep: int) -> dict:
    args = [OPENCODE, "run", "--format", "json"]
    if variant == "without":
        args.append("--pure")
    args.append(PROMPT)
    t0 = time.perf_counter()
    proc = subprocess.run(
        args, cwd=REPO, env={**os.environ, "PWD": REPO}, capture_output=True, text=True, timeout=400
    )
    wall = time.perf_counter() - t0

    tools, text, tok_in, tok_out, steps = [], [], 0, 0, 0
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "tool_use":
            tools.append(part.get("tool"))
        elif ev.get("type") == "text":
            text.append(part.get("text", ""))
        elif ev.get("type") == "step_finish":
            steps += 1
            t = part.get("tokens") or {}
            tok_in += (t.get("input") or 0) + ((t.get("cache") or {}).get("read") or 0)
            tok_out += t.get("output") or 0
    answer = "\n".join(text).strip()
    return {
        "variant": variant,
        "rep": rep,
        "exit": proc.returncode,
        "wall_s": round(wall, 1),
        "steps": steps,
        "tool_calls": len(tools),
        "tools": tools,
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "file_ok": EXPECT["file"] in answer,
        "env_ok": EXPECT["env"] in answer,
        "answer": answer,
    }


if __name__ == "__main__":
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out = []
    for rep in range(1, reps + 1):
        for variant in ("with", "without"):  # interleaved to spread provider latency drift
            r = run(variant, rep)
            out.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "answer"}), flush=True)
    with open("/tmp/ocjit-ab.json", "w") as f:
        json.dump(out, f, indent=2)
