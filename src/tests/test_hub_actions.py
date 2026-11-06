"""Hub action runner with a fake agent command: success, failure, timeout, concurrency limit; no model call."""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

import config
from hub import actions
from hub.actions import agent, report, run_store, runner

FAKE_AGENT = Path(__file__).parent / "fake_hub_agent.py"
SHORT_TIMEOUT = 1.0
SLEEP_SECONDS = 0.8


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv(config.HUB_DIR_ENV, str(tmp_path / "hub"))
    vault = tmp_path / "vault" / "projects"
    vault.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECTS_DIR", vault)
    log_dir = tmp_path / "agent-log"
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log_dir))
    monkeypatch.setenv(agent.AGENT_CMD_ENV, f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_AGENT))}")
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    entry = {"slug": "demo", "path": str(project)}
    return {"entry": entry, "project": project, "vault": vault, "log": log_dir, "tmp": tmp_path}


def calls(log_dir: Path, kind: str):
    return [json.loads(path.read_text()) for path in sorted(log_dir.glob(f"*.{kind}.json"))]


def run_one(env, action="audit360", **runner_kwargs):
    jobs = runner.Runner(**runner_kwargs)
    run = jobs.submit(env["entry"], action)
    # submit() returns the queued snapshot; a worker may already have moved the stored state to running.
    assert run["status"] == run_store.QUEUED and run_store.load(run["id"]) is not None
    jobs.wait_idle()
    return run_store.load(run["id"])


def test_success_saves_report_state_and_obsidian_copy(env):
    final = run_one(env)
    assert final["status"] == agent.SUCCEEDED and final["error"] is None
    assert final["cost"] == 0.0123 and final["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert final["started"] and final["finished"] and final["agent"]["num_turns"] == 4
    day = final["finished"][:10]
    report_path = Path(final["report_path"])
    assert report_path == config.hub_dir() / "reports" / "demo" / f"{day}-audit360.md"
    text = report_path.read_text(encoding="utf-8")
    assert "Raport testowy  z dowodem README.md:1" in text and "\U0001F680" not in text
    assert "# Audyt 360: demo" in text and "0.0123 USD" in text and final["emoji_removed"] == 1
    mirror = Path(final["obsidian_path"])
    assert mirror == env["vault"] / "demo" / "reports" / report_path.name
    assert mirror.read_text(encoding="utf-8") == text
    assert run_store.run_path(final["id"]).parent == config.hub_dir() / "runs"


def test_agent_gets_prompt_on_stdin_in_project_dir_with_read_only_tools(env):
    run_one(env, action="security")
    (call,) = calls(env["log"], "start")
    assert Path(call["cwd"]).resolve() == env["project"].resolve()
    argv = call["argv"][1:]
    assert argv[:3] == ["-p", "--output-format", "json"]
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert allowed == list(agent.ALLOWED_TOOLS)
    assert not {"Edit", "Write", "Bash"} & set(allowed)
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch,Bash"
    assert argv[argv.index("--disallowedTools") + 1] == "Edit,Write,NotebookEdit"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and "--restricted" in argv
    prompt = call["stdin"]
    assert "# Audyt bezpieczeństwa projektu demo" in prompt and "## Zasady" in prompt
    assert f"katalog: `{env['project']}`" in prompt and "$slug" not in prompt


def test_default_command_is_claude_from_path(env, monkeypatch):
    bin_dir = env["tmp"] / "bin"
    bin_dir.mkdir()
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(f"#!{sys.executable}\n" + FAKE_AGENT.read_text(encoding="utf-8"), encoding="utf-8")
    fake_claude.chmod(0o755)
    monkeypatch.delenv(agent.AGENT_CMD_ENV)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert run_one(env, action="market")["status"] == agent.SUCCEEDED
    (call,) = calls(env["log"], "start")
    assert Path(call["argv"][0]).name == "claude" and call["argv"][1] == "-p"


def test_failure_records_exit_code_and_stderr_without_report(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_MODE", "fail")
    final = run_one(env)
    assert final["status"] == agent.FAILED and final["returncode"] == 3
    assert "kodem 3" in final["error"] and "boom: model unavailable" in final["error"]
    assert final["report_path"] is None and final["finished"]
    assert not (config.hub_dir() / "reports").exists() and not (env["vault"] / "demo").exists()


@pytest.mark.parametrize("mode, expected", [("error_result", "error_max_turns"), ("garbage", "nie zwrócił JSON")])
def test_unusable_agent_output_is_a_failure_not_a_report(env, monkeypatch, mode, expected):
    monkeypatch.setenv("FAKE_AGENT_MODE", mode)
    final = run_one(env)
    assert final["status"] == agent.FAILED and expected in final["error"] and final["report_path"] is None
    if mode == "error_result":
        assert final["cost"] == 0.5 and final["usage"] == {"output_tokens": 7}


def test_missing_agent_executable_is_reported(env, monkeypatch):
    monkeypatch.setenv(agent.AGENT_CMD_ENV, str(env["tmp"] / "no-such-agent"))
    final = run_one(env)
    assert final["status"] == agent.FAILED and "nie można uruchomić agenta" in final["error"]


def test_timeout_kills_the_agent(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_MODE", "hang")
    started = time.monotonic()
    final = run_one(env, timeout=SHORT_TIMEOUT)
    assert time.monotonic() - started < agent.KILL_WAIT_SECONDS + 5
    assert final["status"] == agent.TIMEOUT and "limit czasu" in final["error"] and final["report_path"] is None
    assert len(calls(env["log"], "start")) == 1 and calls(env["log"], "end") == []
    pid = int(next(env["log"].glob("*.start.json")).name.split(".")[0])
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_concurrency_limit_queues_the_third_run(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_SLEEP", str(SLEEP_SECONDS))
    jobs = runner.Runner(max_concurrent=2)
    runs = [jobs.submit(env["entry"], action) for action in ("audit360", "security", "market")]
    seen_queued_while_two_run = False
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        statuses = [run_store.load(run["id"])["status"] for run in runs]
        if statuses.count(run_store.RUNNING) == 2 and statuses.count(run_store.QUEUED) == 1:
            seen_queued_while_two_run = True
        assert statuses.count(run_store.RUNNING) <= 2
        if all(status == agent.SUCCEEDED for status in statuses):
            break
        time.sleep(0.02)
    jobs.wait_idle()
    assert seen_queued_while_two_run
    assert all(run_store.load(run["id"])["status"] == agent.SUCCEEDED for run in runs)
    starts = sorted(call["time"] for call in calls(env["log"], "start"))
    ends = sorted(call["time"] for call in calls(env["log"], "end"))
    assert len(starts) == 3 and starts[2] >= ends[0]
    assert sorted(path.name for path in (config.hub_dir() / "reports" / "demo").iterdir()) == sorted(
        f"{run_store.load(run['id'])['finished'][:10]}-{run['action']}.md" for run in runs)


def test_same_action_twice_is_refused_while_active(env, monkeypatch):
    monkeypatch.setenv("FAKE_AGENT_SLEEP", str(SLEEP_SECONDS))
    jobs = runner.Runner()
    first = jobs.submit(env["entry"], "monetization")
    with pytest.raises(runner.ActionBusy):
        jobs.submit(env["entry"], "monetization")
    jobs.wait_idle()
    second = jobs.submit(env["entry"], "monetization")
    jobs.wait_idle()
    paths = [Path(run_store.load(run["id"])["report_path"]).name for run in (first, second)]
    assert paths[0].endswith("-monetization.md") and paths[1].endswith("-monetization-2.md")


def test_unknown_action_and_missing_project_dir(env):
    with pytest.raises(ValueError):
        runner.Runner().submit(env["entry"], "deploy")
    final = run_one({**env, "entry": {"slug": "gone", "path": str(env["tmp"] / "gone")}})
    assert final["status"] == agent.FAILED and "nie istnieje" in final["error"]


def test_runs_of_a_dead_server_are_listed_as_interrupted(env):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    run_store.save({"id": "20260101T000000-market-abcdef", "slug": "demo", "action": "market",
                    "status": run_store.RUNNING, "server_pid": dead.pid})
    run_store.save({"id": "20260102T000000-market-abcdef", "slug": "other", "action": "market",
                    "status": agent.SUCCEEDED, "server_pid": dead.pid})
    (run_store.runs_dir() / "broken.json").write_text("{", encoding="utf-8")
    listed = run_store.list_runs("demo")
    assert [run["status"] for run in listed["runs"]] == [run_store.INTERRUPTED] and listed["unreadable"] == 1
    assert run_store.load("20260101T000000-market-abcdef")["status"] == run_store.INTERRUPTED
    assert [run["slug"] for run in run_store.list_runs()["runs"]] == ["other", "demo"]


def test_templates_exist_for_every_action_and_have_no_emoji():
    for action in actions.ACTIONS:
        text = actions.render_prompt(action, "demo", "/tmp/demo", "2026-11-04")
        assert "##" in text and "plik" in text and "Nie zmieniaj" in text
        assert report.strip_emoji(text)[1] == 0
