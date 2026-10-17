# VibingDiary: audit-driven runtime remediation

## Session
- Date: 2026-10-16
- Goal: repair the live-audit findings in the canonical repository and verify real effects.
- Base commit: `a6c0dfa`; changes are uncommitted and not deployed.
- Status: locally verified. Production trust, queue cleanup, Borg L2 deployment and paired benchmarks remain separate decisions.

## Delivered
- Preserve `CapsuleResult` metadata instead of relying on tuple identity.
- Enforce a final 14,000-character host limit after runtime enrichments, preserving the capsule closing tag.
- Separate generated guidance from direct user instructions; require request-grounded targets and scope-compatible working-set paths.
- Recognize background/MCP notifications; preserve real requests following notices. Store host events as system/authority-zero observations, never user requests.
- Count working-set reads rendered as `(N lines)`.
- Run synthetic invariant and doctor checks in disposable SQLite databases. Health reads actual scope, labels disabled L2, distinguishes self-tests from E2E, and no longer initializes circuit-breaker rows while being read.
- Remove invented token-savings/compression baselines and success claims from CLI, JSON and dashboard. Preserve historical estimates under explicitly named fields; report measured savings as unavailable.
- Read live status only from the configured session directory, without exposing capsule contents or borrowing global legacy temp status.
- Fix hidden-parent workspace discovery and nested-venv wheel smoke-test dependencies.

## Decisions
| Decision | Reason | Rejected alternative |
|---|---|---|
| Preserve typed metadata via `.meta` and legacy tuple compatibility | `CapsuleResult` is a string subclass that supports unpacking, not a tuple | Silently use default budget/complexity |
| Make inferred fields explicitly advisory | A previous working set or a classifier cannot authorize the next task | Label generated instructions as direct-user text |
| Isolate diagnostics | Synthetic user events must never contaminate live memory/replication | Delete historical entries without consent |
| Report unavailable savings as null | No observed paired baseline exists | Assume a fixed 32k/38k counterfactual |
| Exercise hooks in a fresh subprocess HOME | Verify actual imports, persistence, classification and metadata without changing production notes/state | Certify only helper unit tests |
| Retain explicit trust and deployment gates | Audit remediation is not consent to trust repositories or restart production | Auto-trust, silently install or clear outbox |

## Runtime evidence
| Check | Observed result |
|---|---|
| Initial regression tests | 12 failed / 1 passed before implementation |
| Final full suite, supported Python 3.14 | `230 passed in 16.25s`, exit 0 |
| Command | `~/.hermes/cache/scratch/jit-fix-env/bin/python -m pytest src/tests -q --basetemp=~/.hermes/cache/scratch/jit-fix-shipping-check` |
| Real pre-LLM subprocess | Three hook calls: genuine request, background notification, reload notice + genuine request; assertions passed |
| Built wheel | Installed into child venv; CLI, HTTP health and packaged `/live` asset passed |
| Actual dashboard DOM | `Not measured`; `11 / 11 self-tests`; `Local healthy | L2 disabled | E2E not verified` |
| Repeated HTTP health | Three GETs; events/overlay/outbox remained 0/0/0 before and after |
| Hygiene | `git diff --check`, exit 0; new modules <=300 lines and functions <=50 lines |

The operator's local proof bundle is stored outside the repository and is not part of the public release.
Files: `jit-context-fix-verification-2026-10-16.md`, `jit-context-fix-browser-proof-2026-10-16.json`, `jit-context-fix-health-proof-2026-10-16.json`, `jit-context-fix-hook-proof-2026-10-16.json`, `jit-context-fix-pytest-2026-10-16.log`.

## Lessons and limits
- A reported budget overrun can be a metadata-loss bug, not an assembler-cap bypass; trace both layers.
- A nested venv with `system_site_packages=True` does not inherit its parent virtualenv's dependencies. The fixture must deliberately supply its declared prerequisites while checking that imports come from the installed wheel.
- Real historical proofs may remain historical context; they must not become current-task targets or instructions.
- A health HTTP 200 and passing synthetic invariants are not whole-system E2E certification. Surface this distinction in the actual UI.
- Existing unrelated files, local cockpit modifications and the pre-existing commit were preserved. No commit, push, production install, automatic trust, or historic-data deletion was performed.
