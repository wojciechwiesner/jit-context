"""Blind three-arm benchmark on the public synthapse repo: Hermes CLI, same model in every arm.

Arms (everything else identical: model, provider, toolsets, turn limit, prompts):
  off   JIT disabled (state mode "disabled"), context engine passes through -> plain Hermes
  hook  JIT capsule via the pre_llm_call hook, context engine passes through (JIT_ENGINE_DISABLED=1)
  full  JIT capsule + JIT context engine (old bulky tool results elided per request)

Each run gets a fresh git worktree of synthapse HEAD (parked under ~/Projects/active so JIT
resolves the real project scope), optionally with an injected bug committed in it. Scoring is
deterministic and hidden: original test files are restored, hidden vitest files are added after
the agent exits. The agent is never told it is evaluated. Tokens/calls come from ~/.hermes/state.db.

  python3 benchmarks/run_jit_ab_synthapse.py --reps 2 --workers 4
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
REPO = HOME / "Projects/active/synthapse"
REAL_STATE = HOME / ".hermes/state/ona-context"
STATE_DB = HOME / ".hermes/state.db"
AGENT_LOG = HOME / ".hermes/logs/agent.log"
WORK = HOME / "Projects/active/jitbench-synthapse"  # visible dir under Projects/active: worktree .git -> scope synthapse
OUT_DIR = HOME / "Desktop/projects/files/jit-ab-synthapse"
MODEL, PROVIDER = os.environ.get("JITBENCH_MODEL", "claude-opus-5-5"), os.environ.get("JITBENCH_PROVIDER", "a0")
RUN_TIMEOUT_S = 900
ARMS = ("off", "hook", "full")

TEMPO, BEAT = "src/dsp/sessionTempo.ts", "src/dsp/beatDetect.ts"


def _replace(wt: Path, rel: str, old: str, new: str) -> None:
    path = wt / rel
    src = path.read_text()
    assert old in src, f"mutation anchor missing in {rel}: {old!r}"
    path.write_text(src.replace(old, new, 1))


HIDDEN_CONFIDENCE = """import { describe, expect, it } from 'vitest';
import { estimateBpm } from '../src/dsp/beatDetect';
describe('hidden confidence', () => {
  it('stays within 0..1 for a regular pulse', () => {
    const sr = 48000;
    const onsets = Array.from({ length: 33 }, (_, i) => Math.round(i * (60 / 128) * sr));
    const r = estimateBpm(onsets, sr);
    expect(r.bpm).toBe(128);
    expect(r.confidence).toBeGreaterThan(0.5);
    expect(r.confidence).toBeLessThanOrEqual(1);
  });
});
"""

HIDDEN_BEAT_AT = """import { describe, expect, it } from 'vitest';
import { SessionTempo } from '../src/dsp/sessionTempo';
describe('hidden beatAt', () => {
  it('returns null without an anchor', () => { expect(new SessionTempo().beatAt(3)).toBeNull(); });
  it('is anchor + n * period', () => {
    const t = new SessionTempo(); t.lock(120); t.setAnchor(10, 0.9);
    expect(t.beatAt(0)).toBeCloseTo(10); expect(t.beatAt(4)).toBeCloseTo(12); expect(t.beatAt(-2)).toBeCloseTo(9);
  });
});
"""


HIDDEN_LONG = """import { describe, expect, it } from 'vitest';
import { SessionTempo } from '../src/dsp/sessionTempo';
import * as beat from '../src/dsp/beatDetect';
const t0 = () => { const t = new SessionTempo(); t.lock(120); t.setAnchor(10, 0.9); return t; };
describe('hidden long task', () => {
  it('beatAt', () => { expect(t0().beatAt(4)).toBeCloseTo(12); expect(new SessionTempo().beatAt(1)).toBeNull(); });
  it('barAt', () => { expect(t0().barAt(2)).toBeCloseTo(14); expect(t0().barAt(1, 3)).toBeCloseTo(11.5); });
  it('phaseAt', () => {
    expect(t0().phaseAt(10.25)).toBeCloseTo(0.5); expect(t0().phaseAt(9.875)).toBeCloseTo(0.75);
    expect(new SessionTempo().phaseAt(1)).toBeNull();
  });
  it('DEFAULT_BPM_RANGE', () => { expect((beat as any).DEFAULT_BPM_RANGE).toEqual({ minBpm: 110, maxBpm: 160 }); });
});
"""


def score_long(wt: Path, answer: str) -> dict:
    """Hidden checks for the 10-turn task: code (vitest + grep) and recall of turn 2-3 facts."""
    subprocess.run(["git", "checkout", "HEAD", "--", "tests/sessionTempo.test.ts", "tests/beatDetect.test.ts"],
                   cwd=wt, capture_output=True)
    (wt / "tests/hidden_long.test.ts").write_text(HIDDEN_LONG)
    tests_ok, tail = vitest_ok(wt, ["tests/sessionTempo.test.ts", "tests/beatDetect.test.ts", "tests/hidden_long.test.ts"])
    callers = {rel: (wt / rel).read_text() for rel in ("src/dsp/djRuntime.ts", "src/ui/dj.ts")}
    constant_used = all("DEFAULT_BPM_RANGE" in src and "minBpm: 110" not in src for src in callers.values())
    recall = [bool(re.search(p, answer)) for p in (r"djRuntime", r"dj\.ts", r"110", r"160")]
    checks = dict(hidden_tests=tests_ok, constant_used_in_both_callers=constant_used, recall_turn2_3=all(recall))
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.split()
    return dict(passed=all(checks.values()), checks=checks, recall_hits=f"{sum(recall)}/4", detail=tail, changed_files=changed)


TASKS = {
    "bug_anchor": dict(
        category="bugfix",
        setup=lambda wt: _replace(wt, TEMPO, "if (confidence <= MIN_ANCHOR_CONFIDENCE) return;",
                                  "if (confidence < MIN_ANCHOR_CONFIDENCE) return;"),
        turns=["W synthapse beat grid łapie się na beat z pewnością dokładnie 0.5, a nie powinien - "
               "taki anchor ma być odrzucony. Napraw to i upewnij się, że testy przechodzą."],
        tests=["tests/sessionTempo.test.ts"], hidden={}, answer_re=None),
    "bug_confidence": dict(
        category="bugfix",
        setup=lambda wt: _replace(wt, BEAT, "confidence: total ? bestCount / total : 0,",
                                  "confidence: total ? bestCount : 0,"),
        turns=["Detekcja BPM w synthapse zwraca confidence większe niż 1, przez co anchor łapie się na "
               "śmieciach. Znajdź przyczynę, napraw i sprawdź testami."],
        tests=["tests/beatDetect.test.ts"], hidden={"tests/hidden_confidence.test.ts": HIDDEN_CONFIDENCE},
        answer_re=None),
    "feat_beat_at": dict(
        category="feature",
        setup=None,
        turns=["Dodaj do SessionTempo metodę beatAt(n: number): number | null - czas n-tego beatu "
               "liczony od anchora (anchor + n * periodSec), null gdy nie ma anchora. Dopisz test."],
        tests=["tests/sessionTempo.test.ts"], hidden={"tests/hidden_beat_at.test.ts": HIDDEN_BEAT_AT},
        answer_re=None),
    "long_10turn": dict(
        category="long-10-turn",
        setup=None,
        turns=[
            "Przeczytaj src/dsp/sessionTempo.ts i tests/sessionTempo.test.ts. Opisz krótko publiczne API SessionTempo.",
            "Przejrzyj src/dsp/djRuntime.ts: gdzie i z jakimi parametrami wywołuje analyzeBeats i co robi z wynikiem?",
            "To samo dla src/ui/dj.ts: gdzie i z jakimi parametrami wywołuje analyzeBeats?",
            "Dodaj do SessionTempo metodę beatAt(n: number): number | null = anchor + n * periodSec, null bez anchora.",
            "Dodaj barAt(n: number, beatsPerBar = 4): number | null = anchor + n * periodSec * beatsPerBar, null bez anchora.",
            "Dodaj phaseAt(time: number): number | null - pozycja w bieżącym beacie w zakresie [0, 1), "
            "także dla czasów przed anchorem; null bez anchora.",
            "W src/dsp/beatDetect.ts wyeksportuj stałą DEFAULT_BPM_RANGE = { minBpm: 110, maxBpm: 160 } "
            "i użyj jej w obu miejscach wywołania analyzeBeats zamiast literałów.",
            "Dopisz testy vitest dla beatAt, barAt i phaseAt w tests/sessionTempo.test.ts.",
            "Uruchom cały zestaw testów projektu i napraw to, co ewentualnie zepsułeś.",
            "Na koniec: wypisz zmienione pliki oraz przypomnij, w których plikach i z jakim zakresem minBpm/maxBpm "
            "było wcześniej wywoływane analyzeBeats.",
        ],
        tests=[], hidden={}, answer_re=None, scorer=score_long),
    "explore_multiturn": dict(
        category="multi-turn",
        setup=None,
        turns=["Przejrzyj src/dsp/beatDetect.ts i powiedz w dwóch zdaniach, jak liczone jest BPM.",
               "A teraz src/dsp/djRuntime.ts - co robi z wynikiem analizy beatów?",
               "Zajrzyj też do src/ui/dj.ts i src/dsp/sessionTempo.ts.",
               "W których plikach i z jakim zakresem minBpm/maxBpm wywoływane jest analyzeBeats? "
               "Odpowiedz krótko: plik -> zakres."],
        tests=[], hidden={}, answer_re=[r"dj\.ts", r"djRuntime\.ts", r"110", r"160"]),
}


def vitest_ok(wt: Path, files: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(["npx", "vitest", "run", *files], cwd=wt, capture_output=True, text=True, timeout=300)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-600:]


def score(task: str, wt: Path, answer: str) -> dict:
    spec = TASKS[task]
    if spec.get("scorer"):
        return spec["scorer"](wt, answer)
    if spec["answer_re"]:
        hits = [bool(re.search(p, answer)) for p in spec["answer_re"]]
        return dict(passed=all(hits), detail=f"answer patterns {sum(hits)}/{len(hits)}")
    # Restore the original tests (the agent may have weakened them), then add hidden ones.
    subprocess.run(["git", "checkout", "HEAD", "--", *spec["tests"]], cwd=wt, capture_output=True)
    for rel, body in spec["hidden"].items():
        (wt / rel).write_text(body)
    ok, tail = vitest_ok(wt, spec["tests"] + list(spec["hidden"]))
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.split()
    return dict(passed=ok, detail=tail, changed_files=changed)


def repo_fingerprint() -> str:
    """git state plus where node_modules/vitest resolves (catches dependency tampering)."""
    vitest = os.path.realpath(REPO / "node_modules/vitest")
    status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=REPO, capture_output=True, text=True).stdout
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout
    return f"{status}\n{hash(diff)}\n{vitest}"


def prepare_state(arm: str, state_dir: Path) -> None:
    if arm == "off":
        state_dir.mkdir(parents=True)
        (state_dir / "mode.json").write_text(json.dumps({"mode": "disabled"}))
    else:
        subprocess.run(["cp", "-cR", str(REAL_STATE), str(state_dir)], check=True)  # APFS clone, ~0 bytes


def session_metrics(session_id: str) -> dict:
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    row = con.execute("select input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, api_call_count, "
                      "tool_call_count from sessions where id=?", (session_id,)).fetchone()
    con.close()
    keys = ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "api_calls", "tool_calls"]
    if not row:
        return {}
    metrics = dict(zip(keys, row))
    # input_tokens is only the uncached part; with prompt caching the real prompt is the sum.
    metrics["prompt_tokens_total"] = sum(metrics[k] or 0 for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens"))
    return metrics


def engine_log(session_id: str) -> dict:
    lines = [l for l in AGENT_LOG.read_text(errors="replace").splitlines() if f"[{session_id}]" in l]
    elided = [int(m.group(1)) for l in lines if (m := re.search(r"jit engine: elided (\d+)", l))]
    saved = [int(m.group(1)) for l in lines if (m := re.search(r"\(-(\d+)\)", l)) and "jit engine" in l]
    fallback = any("Context engine 'jit' not found" in l for l in lines)
    return dict(engine_selections=len(elided), engine_chars_saved=sum(saved), engine_fallback=fallback)


def capsule_info(state_dir: Path, session_id: str) -> dict:
    files = sorted(state_dir.glob(f"sessions/*/{session_id}/ona_context_*.xml"))
    scope = ""
    if files:
        m = re.search(r'scope="([^"]*)"', files[0].read_text(errors="replace")[:400])
        scope = m.group(1) if m else ""
    return dict(capsule_bytes=max((f.stat().st_size for f in files), default=0), capsule_scope=scope)


def run_one(task: str, arm: str, rep: int) -> dict:
    spec = TASKS[task]
    run_id = f"{task}__{arm}__r{rep}"
    base = WORK / run_id
    if base.exists():
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(base / "wt")], capture_output=True)
        shutil.rmtree(base)
    base.mkdir(parents=True)
    wt, state_dir = base / "wt", base / "state"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), "HEAD"], check=True, capture_output=True)
    # Own node_modules per worktree (APFS clone, ~0 bytes). A symlink to the main repo let an agent's
    # `pnpm install` rewrite the main repo's node_modules into links pointing at a deleted worktree.
    subprocess.run(["cp", "-cR", str(REPO / "node_modules"), str(wt / "node_modules")], check=True)
    if spec["setup"]:
        spec["setup"](wt)
        subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=b", "commit", "-qam", "wip: tempo tweaks"],
                       cwd=wt, check=True)
    prepare_state(arm, state_dir)
    env = {k: v for k, v in os.environ.items() if k not in ("HERMES_SESSION_ID",)}
    env.update(JIT_STATE_DIR=str(state_dir), TERMINAL_CWD=str(wt))
    env["JIT_ENGINE_DISABLED"] = "0" if arm == "full" else "1"

    session_id, turn_log = None, []
    t0 = time.monotonic()
    for i, prompt in enumerate(spec["turns"]):
        cmd = ["hermes", "chat", "-q", prompt, "-Q", "--provider", PROVIDER, "-m", MODEL,
               "-t", "terminal,file", "--yolo", "--source", "jitbench", "--max-turns", "30"]
        if session_id:
            cmd += ["-r", session_id]
        ts = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=wt, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
            out, rc = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, rc = str(exc.stdout or ""), -9
        (base / f"turn{i}.log").write_text(out)
        found = re.findall(r"session_id:\s*(\S+)", out)
        session_id = found[-1] if found else session_id
        turn_log.append(dict(turn=i, rc=rc, wall_s=round(time.monotonic() - ts, 2)))
    wall = round(time.monotonic() - t0, 2)

    answer = ""
    if session_id:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        last = con.execute("select content from messages where session_id=? and role='assistant' and content!='' "
                           "order by id desc limit 1", (session_id,)).fetchone()
        con.close()
        answer = last[0] if last else ""
    result = dict(run_id=run_id, task=task, category=spec["category"], arm=arm, rep=rep, model=MODEL,
                  session_id=session_id, wall_s=wall, turns=turn_log, answer=answer[:1500])
    if session_id:
        result.update(session_metrics(session_id), **engine_log(session_id), **capsule_info(state_dir, session_id))
    result["score"] = score(task, wt, answer)
    (base / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    keep = base / "capsules"
    keep.mkdir()
    for f in state_dir.glob(f"sessions/*/{session_id}/ona_context_*.xml"):
        shutil.copy(f, keep)
    shutil.rmtree(state_dir)
    subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)], capture_output=True)
    print(f"{run_id}: passed={result['score']['passed']} wall={wall}s api={result.get('api_calls')} "
          f"prompt={result.get('prompt_tokens_total')} engine={result.get('engine_selections')} scope={result.get('capsule_scope')}",
          flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=",".join(t for t in TASKS if t != "long_10turn"))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--tag", default="")
    parser.add_argument("--rep-offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    before = repo_fingerprint()
    jobs = [(t, a, r) for r in range(args.rep_offset, args.rep_offset + args.reps) for t in args.tasks.split(",") for a in args.arms.split(",")]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda j: run_one(*j), jobs))
    untouched = repo_fingerprint() == before
    print(f"MAIN_REPO_UNTOUCHED={untouched}")
    for r in results:
        r["main_repo_untouched"] = untouched
    out = OUT_DIR / f"results{('_' + args.tag) if args.tag else ''}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"RESULTS {out}")


if __name__ == "__main__":
    main()
