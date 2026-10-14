"""Per-project skill selection: index, scoring, overrides, determinism, capsule pointers."""

import json
from pathlib import Path

import pytest

from context import skill_index
from context.skill_output import skill_pointers, write_selection
from context.skill_selector import ALWAYS_MUST, select_skills

TS_STACK = {"languages": ["TypeScript"], "frameworks": ["Vite", "React"], "test_runners": ["Vitest"],
            "package_manager": "pnpm"}
PY_STACK = {"languages": ["Python"], "frameworks": ["FastAPI"], "test_runners": ["pytest"]}


def make_skill(root: Path, name: str, description: str, tags: str = "") -> None:
    folder = root / "cat" / name
    folder.mkdir(parents=True)
    tag_line = f"    tags: [{tags}]\n" if tags else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  hermes:\n{tag_line}---\n# {name}\n",
        encoding="utf-8",
    )


@pytest.fixture
def skills_root(tmp_path):
    root = tmp_path / "skills"
    make_skill(root, "vitest-frontend-testing", "Write Vitest tests for React and Vite apps", "vitest, frontend, typescript")
    make_skill(root, "pytest-fixtures-python", "Python pytest fixtures and parametrization", "pytest, python, testing")
    make_skill(root, "verification-before-completion", "Verify before claiming done", "workflow")
    make_skill(root, "systematic-debugging", "Debug methodically", "workflow")
    make_skill(root, "cooking-recipes", "Recipes for pasta", "food")
    archived = root / ".archive" / "old-skill"
    archived.mkdir(parents=True)
    (archived / "SKILL.md").write_text("---\nname: old-skill\ndescription: vitest\n---\n", encoding="utf-8")
    return root


@pytest.fixture
def knowhow_root(tmp_path):
    root = tmp_path / "knowhow"
    root.mkdir()
    (root / "vitest_pitfalls.md").write_text("# Vitest pitfalls\nnotes", encoding="utf-8")
    (root / "pasta.md").write_text("# Pasta\nnotes", encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "webapp"
    path.mkdir()
    return path


def names(picks):
    return [pick.name for pick in picks]


def test_index_skips_archive_and_parses_tags(skills_root):
    skills = {s.name: s for s in skill_index.scan_skills(skills_root)}
    assert "old-skill" not in skills
    assert skills["vitest-frontend-testing"].tags == ("vitest", "frontend", "typescript")


def test_typescript_project_gets_vitest_not_pytest(project, skills_root, knowhow_root):
    selection = select_skills(project, TS_STACK, skills_root, knowhow_root)
    assert "vitest-frontend-testing" in names(selection.must)
    assert "pytest-fixtures-python" not in names(selection.must + selection.optional)
    assert "vitest_pitfalls" in names(selection.knowhow)
    assert "pasta" not in names(selection.knowhow)


def test_python_project_gets_pytest_not_vitest(project, skills_root, knowhow_root):
    selection = select_skills(project, PY_STACK, skills_root, knowhow_root)
    assert "pytest-fixtures-python" in names(selection.must)
    assert "vitest-frontend-testing" not in names(selection.must + selection.optional)


def test_always_must_only_when_skill_exists(project, skills_root, knowhow_root):
    selection = select_skills(project, TS_STACK, skills_root, knowhow_root)
    present = {"verification-before-completion", "systematic-debugging"}
    assert present <= set(names(selection.must))
    missing = set(ALWAYS_MUST) - present
    assert not missing & set(names(selection.must + selection.optional))


def test_override_file_applied_last(project, skills_root, knowhow_root):
    planning = project / ".planning"
    planning.mkdir()
    override = {"must_add": ["cooking-recipes"], "must_remove": ["vitest-frontend-testing"],
                "optional_add": ["pytest-fixtures-python", "no-such-skill"]}
    (planning / "skills.override.json").write_text(json.dumps(override), encoding="utf-8")
    selection = select_skills(project, TS_STACK, skills_root, knowhow_root)
    assert "cooking-recipes" in names(selection.must)
    assert "vitest-frontend-testing" not in names(selection.must + selection.optional)
    assert "pytest-fixtures-python" in names(selection.optional)
    assert "no-such-skill" not in names(selection.must + selection.optional)


def test_selection_is_deterministic(project, skills_root, knowhow_root):
    first = select_skills(project, TS_STACK, skills_root, knowhow_root)
    second = select_skills(project, TS_STACK, skills_root, knowhow_root)
    assert first == second


def test_write_merges_jit_json_and_renders_capsule_pointers(project, skills_root, knowhow_root):
    planning = project / ".planning"
    planning.mkdir()
    (planning / "jit.json").write_text(json.dumps({"small": {"model": "x"}}), encoding="utf-8")
    selection = select_skills(project, TS_STACK, skills_root, knowhow_root)
    write_selection(project, selection)
    profile = json.loads((planning / "jit.json").read_text(encoding="utf-8"))
    assert profile["small"] == {"model": "x"}
    assert profile["skills"]["must"] == names(selection.must)
    assert "vitest-frontend-testing" in (planning / "SKILLS.md").read_text(encoding="utf-8")
    pointers = skill_pointers(str(project))
    assert "@skill:vitest-frontend-testing" in pointers
    assert all(not p.startswith("@skill:") or " " not in p for p in pointers)


def test_pointers_absent_without_profile(project):
    assert skill_pointers(str(project)) == []
