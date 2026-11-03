"""Blind A/B benchmark: Hermes + claude-opus-5-5 with JIT Context OS ON vs OFF.

Each run:
  - gets a fresh git worktree of the faktury repo (HEAD), optionally with an injected bug,
  - gets an isolated JIT state dir (ON = APFS clone of the real state, OFF = mode "disabled"),
  - runs the real `hermes chat -q` CLI (same model, provider, toolsets, turn limit),
  - is scored deterministically (hidden pytest / regex) after the agent exits.

The agent is never told it is being evaluated; prompts are plain user requests.
Metrics come from ~/.hermes/state.db (provider-reported tokens) and wall clock.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
REPO = HOME / "Projects/active/faktury"
VENV = REPO / ".venv"
REAL_STATE = HOME / ".hermes/state/ona-context"
STATE_DB = HOME / ".hermes/state.db"
# JIT resolves project scope from cwd; worktrees outside ~/Projects/active fall back to "general".
WORK = Path(os.environ.get("JITBENCH_WORK", HOME / ".hermes/cache/scratch/jitbench/runs"))
SNAPSHOT = HOME / ".hermes/cache/scratch/jitbench/snap_real"
MODEL, PROVIDER = "claude-opus-5-5", "a0"
RUN_TIMEOUT_S = 900

VAT_FILE = "app/services/llm/vat_parser.py"
NIP_FILE = "app/services/validation/nip_validator.py"

HIDDEN_FORMAT_TEST = '''
import pytest
from app.services.llm.vat_parser import format_vat_rate

@pytest.mark.parametrize("rate,expected", [
    (23.0, "23%"), (8.0, "8%"), (5.5, "5,5%"), (0.0, "0%"), (None, "zw"), (23, "23%"),
])
def test_format_vat_rate(rate, expected):
    assert format_vat_rate(rate) == expected
'''


def mutate_vat(wt: Path) -> None:
    path = wt / VAT_FILE
    src = path.read_text()
    old = 'candidate = cleaned.replace("%", "").replace(",", ".").strip()'
    assert old in src, "vat mutation anchor missing"
    path.write_text(src.replace(old, 'candidate = cleaned.replace("%", "").strip()'))


def mutate_nip(wt: Path) -> None:
    path = wt / NIP_FILE
    src = path.read_text()
    old = 'return nip.format(normalized)  # Returns "XXX-XXX-XX-XX"'
    assert old in src, "nip mutation anchor missing"
    path.write_text(src.replace(old, "return normalized"))


# Realistic commit messages: the injected bug must not be advertised by `git log`.
MUTATION_MSG = {
    "bugfix_vat": "refactor(vat): simplify rate string normalisation",
    "bugfix_nip": "refactor(nip): return normalized value from formatter",
    "multiturn_vat": "refactor(vat): simplify rate string normalisation",
}

TASKS = {
    "bugfix_vat": dict(
        category="coding_bugfix", setup=mutate_vat,
        turns=["Użytkownicy zgłaszają, że stawka VAT wpisana jako '5,5%' albo '8,0' jest odrzucana "
               "(parser zwraca None), a '23%' działa. Znajdź przyczynę i napraw w kodzie."],
    ),
    "bugfix_nip": dict(
        category="coding_bugfix", setup=mutate_nip,
        turns=["Na ekranie faktury NIP kontrahenta wyświetla się jako 5261040828 zamiast "
               "526-104-08-28. Funkcja formatująca NIP chyba się zepsuła - napraw ją."],
    ),
    "feature_format_vat": dict(
        category="coding_feature", setup=None,
        turns=["W module parsera stawek VAT dodaj funkcję format_vat_rate(rate), odwrotność parsowania: "
               "23.0 -> '23%', 5.5 -> '5,5%' (polski przecinek, bez zbędnych zer), 0.0 -> '0%', "
               "None -> 'zw'. Dopisz testy do istniejącego pliku testów parsera."],
    ),
    "qa_prod_port": dict(
        category="project_knowledge", setup=None,
        turns=["Na jakim porcie działa produkcyjna instancja tej aplikacji na serwerze s1 i pod jakim adresem URL?"],
    ),
    "qa_hwm_overlap": dict(
        category="project_knowledge", setup=None,
        turns=["Jaki zapas czasowy (overlap) stosuje synchronizacja KSeF przy High Water Mark i dlaczego?"],
    ),
    "qa_accounting": dict(
        category="project_knowledge", setup=None,
        turns=["Do jakiego systemu księgowego ta aplikacja eksportuje dane? Podaj nazwę produktu i producenta."],
    ),
    "trivial_math": dict(
        category="overhead", setup=None,
        turns=["Ile to 17*23? Odpowiedz samą liczbą."],
    ),
    "multiturn_vat": dict(
        category="multi_turn", setup=mutate_vat,
        turns=[
            "Użytkownicy zgłaszają, że stawka VAT wpisana jako '5,5%' jest odrzucana (parser zwraca None). Napraw.",
            "Dodaj test regresyjny dokładnie na ten przypadek w odpowiednim pliku testów.",
            "Podsumuj w 2 zdaniach co zmieniłeś i w których plikach (ścieżka:linia).",
        ],
    ),
}


def pytest_ok(wt: Path, target: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(VENV / "bin/python"), "-m", "pytest", target, "-q", "-p", "no:cacheprovider"],
        cwd=wt, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]


def hidden_original_ok(wt: Path, target: str) -> tuple[bool, str]:
    pristine = subprocess.run(["git", "show", f"HEAD:{target}"], cwd=REPO, capture_output=True, text=True).stdout
    hidden = wt / "tests" / ("test_zz_hidden_" + Path(target).name.removeprefix("test_"))
    hidden.write_text(pristine)
    return pytest_ok(wt, str(hidden.relative_to(wt)))


def git_diff_names(wt: Path) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def score(task: str, wt: Path, answer: str) -> dict:
    changed = git_diff_names(wt)
    if task in ("bugfix_vat", "bugfix_nip"):
        # Agents may legitimately edit/strengthen tests; grade on a hidden pristine copy.
        target = "tests/test_vat_parser.py" if task == "bugfix_vat" else "tests/test_validators.py"
        ok, tail = hidden_original_ok(wt, target)
        return dict(passed=ok, detail=tail, changed=changed)
    if task == "feature_format_vat":
        own_ok, own_tail = pytest_ok(wt, "tests/test_vat_parser.py")
        hidden = wt / "tests/test_zz_hidden_format_vat.py"
        hidden.write_text(HIDDEN_FORMAT_TEST)
        hid_ok, hid_tail = pytest_ok(wt, str(hidden.relative_to(wt)))
        added_tests = "format_vat_rate" in (wt / "tests/test_vat_parser.py").read_text()
        return dict(passed=own_ok and hid_ok and added_tests, detail=f"own:{own_tail} | hidden:{hid_tail}",
                    added_tests=added_tests, changed=changed)
    if task == "multiturn_vat":
        ok, tail = hidden_original_ok(wt, "tests/test_vat_parser.py")
        test_src = (wt / "tests/test_vat_parser.py").read_text()
        regression = "5,5" in subprocess.run(["git", "diff", "tests/"], cwd=wt, capture_output=True, text=True).stdout
        summary_ok = "vat_parser.py" in answer
        return dict(passed=ok and regression and summary_ok, detail=tail, regression_test=regression,
                    summary_mentions_file=summary_ok, changed=changed, test_len=len(test_src))
    low = answer.lower()
    if task == "qa_prod_port":
        return dict(passed="8002" in low and "invoiceflow.apppartner.pl" in low, changed=changed)
    if task == "qa_hwm_overlap":
        return dict(passed=bool(re.search(r"\b(2|dwa|dwóch|two)\s*(dni|days?|dób)", low)) or "timedelta(days=2)" in low,
                    changed=changed)
    if task == "qa_accounting":
        return dict(passed="optima" in low and "comarch" in low, changed=changed)
    if task == "trivial_math":
        return dict(passed="391" in answer, changed=changed)
    raise ValueError(task)


def main_repo_fingerprint() -> str:
    """Status + content hash of dirty files in the main repo (detects agent leaks)."""
    status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=REPO,
                            capture_output=True, text=True).stdout
    digest = subprocess.run(["git", "diff", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout
    untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    sizes = [f"{p}:{(REPO / p).stat().st_size}" for p in untracked if (REPO / p).is_file()]
    return f"{status}\n{hash(digest)}\n{sizes}"


def prepare_state(arm: str, state_dir: Path) -> None:
    if arm == "on":
        subprocess.run(["cp", "-cR", str(SNAPSHOT), str(state_dir)], check=True)
    else:
        state_dir.mkdir(parents=True)
        (state_dir / "mode.json").write_text(json.dumps({"mode": "disabled"}))


def session_metrics(session_id: str) -> dict:
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    row = con.execute(
        "select input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, api_call_count, "
        "tool_call_count from sessions where id=?", (session_id,)).fetchone()
    tools = con.execute(
        "select tool_name, count(*) from messages where session_id=? and role='tool' group by tool_name",
        (session_id,)).fetchall()
    con.close()
    keys = ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "api_calls", "tool_calls"]
    data = dict(zip(keys, row)) if row else {}
    data["tools_by_name"] = dict(tools)
    return data


def capsule_sizes(state_dir: Path, session_id: str) -> int:
    files = list(state_dir.glob(f"sessions/*/{session_id}/ona_context_{session_id}.xml"))
    return max((f.stat().st_size for f in files), default=0)


def run_one(task: str, arm: str, rep: int) -> dict:
    spec = TASKS[task]
    run_id = f"{task}__{arm}__r{rep}"
    base = WORK / run_id
    if base.exists():
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(base / "wt")], capture_output=True)
        shutil.rmtree(base)
    base.mkdir(parents=True)
    wt, state_dir = base / "wt", base / "state"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), "HEAD"],
                   check=True, capture_output=True)
    (wt / ".venv").symlink_to(VENV)
    if spec["setup"]:
        spec["setup"](wt)
        subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
        subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=b", "commit", "-qm", MUTATION_MSG[task]], cwd=wt, check=True)
    prepare_state(arm, state_dir)
    # TERMINAL_CWD leaks from the parent Hermes session and would make the child
    # agent edit the main repo instead of its worktree - pin it per run.
    env = {k: v for k, v in os.environ.items() if k not in ("HERMES_SESSION_ID",)}
    env.update(JIT_STATE_DIR=str(state_dir), TERMINAL_CWD=str(wt))

    session_id, answer, turn_log = None, "", []
    t0 = time.monotonic()
    for i, prompt in enumerate(spec["turns"]):
        cmd = ["hermes", "chat", "-q", prompt, "-Q", "--provider", PROVIDER, "-m", MODEL,
               "-t", "terminal,file", "--yolo", "--source", "jitbench", "--max-turns", "30"]
        if session_id:
            cmd += ["-r", session_id]
        ts = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=wt, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
            out = proc.stdout + proc.stderr
            rc = proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, rc = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), -9
        (base / f"turn{i}.log").write_text(out)
        m = re.findall(r"session_id:\s*(\S+)", out)
        session_id = m[-1] if m else session_id
        turn_log.append(dict(turn=i, rc=rc, wall_s=round(time.monotonic() - ts, 2)))
    wall = round(time.monotonic() - t0, 2)

    if session_id:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        last = con.execute("select content from messages where session_id=? and role='assistant' and content!='' "
                           "order by id desc limit 1", (session_id,)).fetchone()
        con.close()
        answer = last[0] if last else ""
    result = dict(run_id=run_id, task=task, category=spec["category"], arm=arm, rep=rep,
                  session_id=session_id, wall_s=wall, turns=turn_log,
                  capsule_bytes=capsule_sizes(state_dir, session_id) if session_id else 0,
                  answer=answer[:1500])
    result.update(session_metrics(session_id) if session_id else {})
    result["score"] = score(task, wt, answer)
    (base / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    # Free the cloned 840 MB state; keep capsule XMLs for audit.
    keep = base / "capsules"
    keep.mkdir()
    for f in state_dir.glob(f"sessions/*/{session_id}/ona_context_*.xml"):
        shutil.copy(f, keep)
    shutil.rmtree(state_dir)
    subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)], capture_output=True)
    print(f"{run_id}: passed={result['score']['passed']} wall={wall}s api={result.get('api_calls')} "
          f"tools={result.get('tool_calls')} capsule={result['capsule_bytes']}B", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=",".join(TASKS))
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    assert SNAPSHOT.exists(), f"missing JIT state snapshot {SNAPSHOT}"
    WORK.mkdir(parents=True, exist_ok=True)
    main_before = main_repo_fingerprint()
    jobs = [(t, arm, r) for r in range(args.reps) for t in args.tasks.split(",") for arm in ("on", "off")]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda j: run_one(*j), jobs))
    leaked = main_repo_fingerprint() != main_before
    print(f"MAIN_REPO_UNTOUCHED={not leaked}")
    for r in results:
        r["main_repo_leak_during_batch"] = leaked
    out = SNAPSHOT.parent / f"results_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"RESULTS {out}")


if __name__ == "__main__":
    main()
