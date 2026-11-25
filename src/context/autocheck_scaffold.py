"""sota-starter Autocheck step for `jit init`.

Creates the per-project probe folder `.planning/autocheck/` with a README that explains the contract
(run by the `autocheck-flow` engine in ~/Projects/active/autocheck, Hermes cron every 30 min).
It never writes `.planning/autocheck.json` and never invents a probe URL: a status file only exists
after a real probe run, so the cockpit cannot show a paper certification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Union

ScaffoldResult = Dict[str, Union[str, bool, List[str]]]

PROBE_DIR_NAME = "autocheck"
README_NAME = "README.md"
STATUS_FILE_NAME = "autocheck.json"

PROBE_README = """# Autocheck probes

One `.hurl` file = one flow. Every step must answer 2xx/3xx within `@step_max_seconds`.
The Hermes cron `autocheck-flows-sync` (every 30 min) runs all probes of every project registered
in the JIT hub and writes the result to `.planning/autocheck.json` (shown in `.planning/state.html`).

```
# @base_url: http://127.0.0.1:8000
# @step_max_seconds: 5

# @node: health
GET {{base_url}}/health
HTTP 200
```

Commands (engine: `~/Projects/active/autocheck`, `python3 -m autocheck_flow ...`):

- `scaffold <project> --url <real health URL> [--flow-id health]` - create a probe for one URL
- `probe <project> [--write]` - run the probes now (exit 1 when any flow is not ok)

Rules: probe real, running endpoints only; no placeholder URLs; no secrets in `.hurl` files.
"""


def ensure_autocheck_scaffold(project_dir: Path) -> ScaffoldResult:
    """Create .planning/autocheck/README.md if missing; report how many probes the project has."""
    probe_dir = Path(project_dir) / ".planning" / PROBE_DIR_NAME
    probe_dir.mkdir(parents=True, exist_ok=True)
    readme = probe_dir / README_NAME
    created = not readme.exists()
    if created:
        readme.write_text(PROBE_README, encoding="utf-8")
    probes = sorted(p.name for p in probe_dir.glob("*.hurl"))
    status_file = Path(project_dir) / ".planning" / STATUS_FILE_NAME
    return {
        "probe_dir": str(probe_dir),
        "readme_created": created,
        "probes": probes,
        "status_file_exists": status_file.is_file(),
    }


def autocheck_init_line(result: ScaffoldResult) -> str:
    probes = result.get("probes")
    probes = probes if isinstance(probes, list) else []
    if probes:
        return f"Autocheck: {len(probes)} probe(s) in {result['probe_dir']}"
    return (f"Autocheck: no probes yet - add one with `python3 -m autocheck_flow scaffold <project> --url <health URL>` "
            f"(see {result['probe_dir']}/README.md)")
