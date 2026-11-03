"""Aggregate run_jit_ab_opus55.py results into a per-category ON vs OFF comparison."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

METRICS = ["wall_s", "api_calls", "tool_calls", "input_tokens", "cache_read_tokens",
           "cache_write_tokens", "output_tokens", "capsule_bytes"]


def total_prompt_tokens(r: dict) -> int:
    return (r.get("input_tokens") or 0) + (r.get("cache_read_tokens") or 0) + (r.get("cache_write_tokens") or 0)


def summarize(rows: list[dict]) -> dict:
    out: dict[str, float] = {"n": len(rows), "pass": sum(1 for r in rows if r["score"]["passed"])}
    for m in METRICS + ["prompt_tokens"]:
        vals = [total_prompt_tokens(r) if m == "prompt_tokens" else (r.get(m) or 0) for r in rows]
        out[m] = statistics.median(vals) if vals else 0
        out[m + "_sum"] = sum(vals)
    return out


def fmt_row(label: str, on: dict, off: dict) -> str:
    def delta(key: str) -> str:
        if not off[key]:
            return "n/a"
        return f"{(on[key] - off[key]) / off[key] * 100:+.0f}%"
    return (f"{label:<20} pass ON {on['pass']}/{on['n']} OFF {off['pass']}/{off['n']} | "
            f"wall med {on['wall_s']:.0f}s vs {off['wall_s']:.0f}s ({delta('wall_s')}) | "
            f"api {on['api_calls']:.0f} vs {off['api_calls']:.0f} ({delta('api_calls')}) | "
            f"tools {on['tool_calls']:.0f} vs {off['tool_calls']:.0f} ({delta('tool_calls')}) | "
            f"prompt tok {on['prompt_tokens']/1000:.0f}k vs {off['prompt_tokens']/1000:.0f}k ({delta('prompt_tokens')}) | "
            f"out tok {on['output_tokens']:.0f} vs {off['output_tokens']:.0f} ({delta('output_tokens')})")


def main(path: str) -> None:
    rows = json.loads(Path(path).read_text())
    by_task, by_cat = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_task[r["task"]][r["arm"]].append(r)
        by_cat[r["category"]][r["arm"]].append(r)
    print("== PER TASK (medians) ==")
    for task in sorted(by_task):
        print(fmt_row(task, summarize(by_task[task]["on"]), summarize(by_task[task]["off"])))
    print("\n== PER CATEGORY (medians) ==")
    for cat in sorted(by_cat):
        print(fmt_row(cat, summarize(by_cat[cat]["on"]), summarize(by_cat[cat]["off"])))
    on_all = summarize([r for r in rows if r["arm"] == "on"])
    off_all = summarize([r for r in rows if r["arm"] == "off"])
    print("\n== OVERALL ==")
    print(fmt_row("ALL", on_all, off_all))
    print(f"SUMS  wall {on_all['wall_s_sum']:.0f}s vs {off_all['wall_s_sum']:.0f}s | "
          f"prompt tok {on_all['prompt_tokens_sum']} vs {off_all['prompt_tokens_sum']} | "
          f"out tok {on_all['output_tokens_sum']} vs {off_all['output_tokens_sum']}")
    leak = any(r.get("main_repo_leak_during_batch") for r in rows)
    print(f"main repo leak during batch: {leak}")


if __name__ == "__main__":
    main(sys.argv[1])
