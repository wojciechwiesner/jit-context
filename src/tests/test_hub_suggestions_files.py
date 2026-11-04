"""Suggestion rules over tracked files and STATE.md blockers, plus the engine contract (sorting, skipped, errors)."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from hub import suggestion_rules_files as rules
from hub import suggestions
from hub.suggestion_model import SEVERITY_HIGH, SEVERITY_LOW, ProjectContext, Suggestion, value_evidence
from hub.suggestion_state import open_blockers

NOW = datetime(2026, 11, 4, 12, 0, 0)
TEMPLATE_BLOCKERS = "## Blockers\n| ID | Blocker | Impact | Owner / action | Status |\n|---|---|---|---|---|\n"


def make_repo(tmp_path: Path, files: dict) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    env = dict(os.environ, GIT_AUTHOR_DATE=NOW.isoformat(), GIT_COMMITTER_DATE=NOW.isoformat())
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
                        "-c", "core.hooksPath=/dev/null", *args], cwd=repo, env=env, check=True, capture_output=True)
    return repo


def ctx(repo: Path) -> ProjectContext:
    return ProjectContext(repo, now=NOW)


def lines(count: int) -> str:
    return "x = 1\n" * count


def test_large_files_lists_top_five_and_skips_vendor(tmp_path):
    files = {f"src/m{i}.py": lines(301 + i) for i in range(6)}
    files["vendor/lib.js"] = lines(5000)
    files["src/ok.py"] = lines(rules.MAX_FILE_LINES)
    found = rules.large_files(ctx(make_repo(tmp_path, files)))
    assert found is not None and found.summary.startswith("6 plików")
    assert [item.ref for item in found.evidence] == ["src/m5.py", "src/m4.py", "src/m3.py", "src/m2.py", "src/m1.py"]
    assert found.evidence[0].value == "306 linii"


def test_large_files_quiet_at_limit(tmp_path):
    repo = make_repo(tmp_path, {"src/ok.py": lines(rules.MAX_FILE_LINES), "data/big.txt": lines(900)})
    assert rules.large_files(ctx(repo)) is None


def test_no_tests_fires_without_tests_or_command(tmp_path):
    repo = make_repo(tmp_path, {"src/app.js": "1\n", "package.json": json.dumps(
        {"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}})})
    found = rules.no_tests(ctx(repo))
    assert found is not None and found.severity == SEVERITY_HIGH
    assert found.summary == "Brak testów ani komendy testowej w repozytorium."
    js_only = make_repo(tmp_path / "js", {"src/__tests__/app.test.js": "1\n"})
    partial = rules.no_tests(ctx(js_only))
    assert partial is not None and partial.summary == "Brak komendy testowej w repozytorium."


def test_no_tests_quiet_with_tests_and_command(tmp_path):
    assert rules.no_tests(ctx(make_repo(tmp_path, {"tests/test_app.py": "def test_x(): pass\n"}))) is None
    js = make_repo(tmp_path / "js", {"src/app.test.ts": "1\n", "package.json": '{"scripts": {"test": "vitest"}}'})
    assert rules.no_tests(ctx(js)) is None


def test_readme_quickstart_fires_without_readme_or_section(tmp_path):
    missing = rules.readme_quickstart(ctx(make_repo(tmp_path, {"app.py": "1\n"})))
    assert missing is not None and missing.evidence[0].value == "brak pliku"
    plain = rules.readme_quickstart(ctx(make_repo(tmp_path / "b", {"README.md": "# App\n\nOpis.\n## API\n"})))
    assert plain is not None and plain.summary == "README.md nie ma sekcji Quickstart."


def test_readme_quickstart_quiet_with_section(tmp_path):
    for heading in ("## Quickstart", "## Szybki start", "### Getting started"):
        repo = make_repo(tmp_path / heading.split()[-1], {"README.md": f"# App\n\n{heading}\n\npip install .\n"})
        assert rules.readme_quickstart(ctx(repo)) is None


def test_open_blockers_found_in_table_checklist_and_tag(tmp_path):
    state = (TEMPLATE_BLOCKERS + "| B1 | Brak dostępu do API | stoi deploy | Wojciech | open |\n\n"
             "## Plan\n- [ ] T2 [bloker] czekamy na klucze\n- [ ] T3 zwykłe zadanie\n")
    found = rules.open_blockers(ctx(make_repo(tmp_path, {".planning/STATE.md": state})))
    assert found is not None and found.severity == SEVERITY_HIGH
    assert [item.value for item in found.evidence] == ["B1: Brak dostępu do API", "T2 [bloker] czekamy na klucze"]


def test_open_blockers_quiet_for_template_closed_and_placeholders(tmp_path):
    state = (TEMPLATE_BLOCKERS + "| B1 | | | | |\n| B2 | Stary problem | - | - | resolved |\n\n"
             "## Blokery\n- [x] B3 naprawione\n- brak\n\n## Plan\n- [ ] T1 zwykłe zadanie\n")
    assert open_blockers(state) == []
    assert rules.open_blockers(ctx(make_repo(tmp_path, {".planning/STATE.md": state}))) is None


def test_engine_sorts_by_severity_and_reports_skipped_and_errors(tmp_path):
    def low(_ctx):
        return Suggestion("low_rule", SEVERITY_LOW, "s", "a", (value_evidence("v", 1),))

    def high(_ctx):
        return Suggestion("high_rule", SEVERITY_HIGH, "s", "a", (value_evidence("v", 2),))

    def broken(_ctx):
        raise ValueError("boom")

    repo = make_repo(tmp_path, {"app.py": "1\n"})
    report = suggestions.evaluate(ctx(repo), rules=(
        ("low_rule", low), ("broken", broken), ("open_blockers", rules.open_blockers), ("high_rule", high)))
    assert [s["id"] for s in report["suggestions"]] == ["high_rule", "low_rule"]
    assert report["skipped"] == [{"id": "open_blockers", "reason": "brak .planning/STATE.md"}]
    assert report["errors"] == [{"id": "broken", "error": "ValueError: boom"}]
    assert set(report["suggestions"][0]) == {"id", "severity", "summary", "action", "evidence"}
    assert report["suggestions"][0]["evidence"] == [{"kind": "value", "ref": "v", "value": "2"}]


def test_full_report_on_clean_repo_has_every_rule_accounted_for(tmp_path):
    repo = make_repo(tmp_path, {".planning/STATE.md": "# S\n- [x] done\n", "README.md": "## Quickstart\nrun\n",
                                "tests/test_app.py": "def test_x(): pass\n", "app.py": "1\n"})
    report = suggestions.project_suggestions(repo, slug="proj", now=NOW, usage_db=tmp_path / "absent.sqlite",
                                             projects=[])
    accounted = {s["id"] for s in report["suggestions"]} | {s["id"] for s in report["skipped"]}
    assert report["suggestions"] == [] and report["errors"] == []
    assert accounted == {"architecture_drift", "usage_spike", "jit_mostly_off"}
    assert report["rules_checked"] == len(suggestions.RULES)
