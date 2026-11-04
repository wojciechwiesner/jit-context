"""Plain-text report of `jit hub usage`: what was collected, source errors and per project totals."""

from __future__ import annotations

from typing import Dict, List, Tuple

from hub.usage import CollectResult
from hub.usage_store import SUM_FIELDS

UNATTRIBUTED = "(bez projektu)"
NOT_REGISTERED = " [spoza rejestru]"
UNKNOWN_COST = "brak"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
MAX_ERRORS_SHOWN = 5


def _totals(rows: List[dict]) -> Dict[Tuple[str, str], dict]:
    totals: Dict[Tuple[str, str], dict] = {}
    for row in rows:
        label = (row["project"] or UNATTRIBUTED) + ("" if row["registered"] else NOT_REGISTERED)
        bucket = totals.setdefault((label, row["source"]), {name: 0 for name in SUM_FIELDS})
        bucket.setdefault("sessions", 0)
        bucket.setdefault("cost_usd", None)
        for name in SUM_FIELDS:
            bucket[name] += row[name]
        bucket["sessions"] += row["sessions"]
        if row["cost_usd"] is not None:
            bucket["cost_usd"] = (bucket["cost_usd"] or 0.0) + row["cost_usd"]
    return totals


def _line(label: str, source: str, bucket: dict) -> str:
    cost = UNKNOWN_COST if bucket["cost_usd"] is None else f"${bucket['cost_usd']:.2f}"
    tokens = "  ".join(f"{bucket[name]:>12,}" for name in TOKEN_FIELDS)
    extra = f"  kapsuły {bucket['capsules']}" if source == "jit" else ""
    counts = f"sesje-dni {bucket['sessions']:>4}  tury {bucket['turns']:>5}"
    return f"  {label:<40} {source:<7} {counts}  {tokens}  koszt {cost}{extra}"


def render(result: CollectResult, rows: List[dict], days: int) -> str:
    """Polish text report; source errors are listed, never hidden."""
    added = ", ".join(f"{source} {count}" for source, count in result.added.items())
    lines = [f"Hub usage: ostatnie {days} dni", f"  Nowe dane w tym przebiegu: {added}"]
    for source, errors in result.errors.items():
        lines.append(f"  ! {source}: błędów {len(errors)}")
        lines.extend(f"      {error}" for error in errors[:MAX_ERRORS_SHOWN])
    if not rows:
        lines.append("  Brak danych o zużyciu w tym okresie.")
        return "\n".join(lines)
    lines.append("  Kolumny tokenów: input, output, cache-read, cache-write. Koszt tylko z Hermesa.")
    for (label, source), bucket in sorted(_totals(rows).items()):
        lines.append(_line(label, source, bucket))
    return "\n".join(lines)
