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
CONTRACTS_FILE_NAME = "contracts.yaml"

CONTRACTS_TEMPLATE = """# Behavior contracts: "when X happens, Y (and Z) must follow" - checked on REAL production data.
# Each sql is ONE read-only SELECT that returns VIOLATIONS (rows where X happened but Y did not).
# First column = record id shown in the alert. Empty result = the function works.
# Run:   python3 -m autocheck_flow contracts run .      (engine: ~/Projects/active/autocheck)
# Cron:  every 30 min, Telegram Infra alert only when something changes.
# Spec:  ~/Projects/active/autocheck/docs/CONTRACTS_SPEC.md
# Nothing below is active until you uncomment it and point it at a read-only source.
#
# project: my-app
# sources:
#   prod:
#     kind: postgres            # postgres (via: ssh | dsn) or sqlite (path:)
#     via: ssh
#     ssh_host: borg-ts
#     command: docker exec -i my-app-db psql -U readonly_user -d my_app
# contracts:
#   - id: order_paid_has_confirmation_email
#     when: Klient oplacil zamowienie
#     then: w 10 min dostal e-mail z potwierdzeniem
#     source: prod
#     severity: high            # high | medium -> Telegram; low -> cockpit only
#     sql: |
#       select o.id from orders o
#       where o.status = 'paid' and o.paid_at < now() - interval '10 minutes'
#         and not exists (select 1 from emails e where e.order_id = o.id and e.kind = 'confirmation')
"""

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
    contracts_file = Path(project_dir) / ".planning" / CONTRACTS_FILE_NAME
    contracts_created = not contracts_file.exists()
    if contracts_created:
        contracts_file.write_text(CONTRACTS_TEMPLATE, encoding="utf-8")
    probes = sorted(p.name for p in probe_dir.glob("*.hurl"))
    status_file = Path(project_dir) / ".planning" / STATUS_FILE_NAME
    return {
        "probe_dir": str(probe_dir),
        "readme_created": created,
        "contracts_file": str(contracts_file),
        "contracts_created": contracts_created,
        "probes": probes,
        "status_file_exists": status_file.is_file(),
    }


def autocheck_init_line(result: ScaffoldResult) -> str:
    probes = result.get("probes")
    probes = probes if isinstance(probes, list) else []
    probe_part = (f"{len(probes)} probe(s) in {result['probe_dir']}" if probes else
                  "no probes yet - `python3 -m autocheck_flow scaffold <project> --url <health URL>`")
    return (f"Autocheck: {probe_part}; behavior contracts: {result.get('contracts_file')} "
            f"(\"when X -> Y\" on real data, see the commented example)")
