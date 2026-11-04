"""Plain-text report of `jit hub compare`: per project and day, JIT on vs off medians with group sizes."""

from __future__ import annotations

from typing import List, Optional

from hub.jit_compare import JIT_OFF, JIT_ON, METRICS

UNATTRIBUTED = "(bez projektu)"
NOT_REGISTERED = " [spoza rejestru]"
MISSING = "brak danych"
GROUP_TITLES = {JIT_ON: "JIT wł.", JIT_OFF: "JIT wył."}
METRIC_TITLES = {
    "tokens_per_turn": "tokeny/tura",
    "cache_read_share": "udział cache-read",
    "turns_per_session": "tury/sesja",
    "tool_errors_per_session": "błędy narzędzi/sesja",
}
PERCENT = 100


def _value(name: str, value: Optional[float]) -> str:
    if value is None:
        return MISSING
    if name == "cache_read_share":
        return f"{value * PERCENT:.1f}%"
    return f"{value:,.1f}"


def _group_line(key: str, group: dict) -> str:
    sources = ", ".join(f"{source} {count}" for source, count in sorted(group["sources"].items())) or "-"
    cells = []
    for name in METRICS:
        metric = group["metrics"][name]
        cells.append(f"{METRIC_TITLES[name]} {_value(name, metric['median'])} (n={metric['n']})")
    return f"    {GROUP_TITLES[key]:<9} n={group['n']:<4} [{sources}]  " + "  ".join(cells)


def _row_lines(row: dict) -> List[str]:
    label = (row["project"] or UNATTRIBUTED) + ("" if row["registered"] else NOT_REGISTERED)
    warning = f"  {row['warning']}" if row["warning"] else ""
    return [f"  {row['day']}  {label}{warning}", _group_line(JIT_ON, row[JIT_ON]), _group_line(JIT_OFF, row[JIT_OFF])]


def render(comparison: dict, collect_errors: Optional[dict] = None) -> str:
    """Polish text report; the observation label and source errors are always printed."""
    since = comparison["since"] or "wszystkie dni"
    lines = [f"Porównanie JIT wł./wył. ({comparison['label']}), od: {since}",
             f"  Mediany na sesję-dzień. Poniżej n={comparison['min_group_n']} w którejkolwiek grupie: "
             f"\"{comparison['low_n_label']}\". Brak wyliczeń oszczędności: tylko test A/B."]
    for source, errors in (collect_errors or {}).items():
        lines.append(f"  ! {source}: błędów {len(errors)}")
    if not comparison["rows"]:
        lines.append("  Brak sesji w tym okresie.")
        return "\n".join(lines)
    for row in comparison["rows"]:
        lines.extend(_row_lines(row))
    return "\n".join(lines)
