"""Suggestions engine: deterministic rules over one project, each finding with id, severity, evidence and one
recommended action in Polish.

Every rule returns None (checked, nothing to suggest) or a Suggestion, and raises MissingData when its input does
not exist; those rules are listed under "skipped" with the reason, never guessed. A rule that crashes is listed
under "errors" and the remaining rules still run. No model is called here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from hub import suggestion_rules_files as files
from hub import suggestion_rules_git as git_rules
from hub import suggestion_rules_usage as usage
from hub.suggestion_model import SEVERITY_ORDER, MissingData, ProjectContext, Suggestion

Rule = Callable[[ProjectContext], Optional[Suggestion]]
ERROR_TEXT_LIMIT = 300

RULES: Tuple[Tuple[str, Rule], ...] = (
    ("state_stale", git_rules.state_stale),
    ("architecture_drift", git_rules.architecture_stale),
    ("cockpit_tracked", git_rules.cockpit_tracked),
    ("large_files", files.large_files),
    ("no_tests", files.no_tests),
    ("changelog_stale", git_rules.changelog_stale),
    ("readme_quickstart", files.readme_quickstart),
    ("env_tracked", git_rules.env_tracked),
    ("open_blockers", files.open_blockers),
    ("inactive_with_open_tasks", git_rules.inactive_with_open_tasks),
    ("usage_spike", usage.usage_spike),
    ("jit_mostly_off", usage.jit_mostly_off),
)


def evaluate(ctx: ProjectContext, rules: Tuple[Tuple[str, Rule], ...] = RULES) -> dict:
    """Run the rules; suggestions are sorted by severity, then by rule order."""
    found: List[Suggestion] = []
    skipped: List[dict] = []
    errors: List[dict] = []
    for rule_id, rule in rules:
        try:
            suggestion = rule(ctx)
        except MissingData as missing:
            skipped.append({"id": rule_id, "reason": missing.reason})
            continue
        except Exception as exc:  # one broken rule must not hide the others
            errors.append({"id": rule_id, "error": f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT]})
            continue
        if suggestion is not None:
            found.append(suggestion)
    order = {rule_id: index for index, (rule_id, _) in enumerate(rules)}
    found.sort(key=lambda s: (SEVERITY_ORDER.get(s.severity, len(SEVERITY_ORDER)), order.get(s.rule_id, 0)))
    return {
        "project": str(ctx.path), "generated_at": ctx.now.isoformat(timespec="seconds"),
        "rules_checked": len(rules), "suggestions": [s.to_dict() for s in found],
        "skipped": skipped, "errors": errors,
    }


def project_suggestions(path: Path, slug: Optional[str] = None, now: Optional[datetime] = None,
                        usage_db: Optional[Path] = None, projects: Optional[List[dict]] = None) -> dict:
    """Suggestions for one project; usage rules read the hub usage store for `slug`."""
    now = now or datetime.now()
    view, missing, error = None, None, None
    try:
        view = usage.load_usage(slug, now.date(), db_path=usage_db, projects=projects)
    except MissingData as exc:
        missing = exc.reason
    except Exception as exc:  # unreadable store: both usage rules report it as their error
        error = f"usage store: {type(exc).__name__}: {exc}"
    report = evaluate(ProjectContext(Path(path), now=now, usage=view, usage_missing=missing, usage_error=error))
    report["slug"] = slug
    return report
