#!/usr/bin/env python3
"""SWE-bench Verified agent loop, protocol v2 (small-model harness).

Differences vs the v1 `jit` arm in agent.py (everything else is reused as-is:
checkout, read/search/find tools, output capping, loop guard, working set):
  P1  Tool selection uses the provider's native function calling; code edits are
      plain-text SEARCH/REPLACE blocks in the message body, never JSON strings.
  P3  After every edit the harness checks syntax (reverts on error), reports new
      pyflakes warnings and echoes the resulting diff hunk. `finish` on an empty
      diff is rejected once.

No gold tests or hidden information are used; grading stays with the official
swebench harness.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import agent as v1
from v2_edits import apply_edit, diff_hunk, new_flakes, parse_edits, resolve_path, syntax_error

SYSTEM = """You are fixing a bug in a Python repository checked out in the current directory.

Use the provided functions to explore: search, find_file, read_file, finish.

To EDIT code, do not call a function. Write one or more SEARCH/REPLACE blocks in your reply.
The first line is the real repository path of the file, exactly as printed by search or read_file:

astropy/io/fits/card.py
<<<<<<< SEARCH
        value = self._parse_value()
=======
        value = self._parse_value(strict=False)
>>>>>>> REPLACE

Rules:
- SEARCH copies existing lines exactly (enough lines to be unique), with their indentation and WITHOUT line numbers.
  Code is plain text: no escaping, no JSON.
- After each edit you get the syntax check result and the resulting diff. Read it before calling finish.
- Do not modify test files. Make the minimal fix, then call finish."""

TOOLS = [
    {"type": "function", "function": {
        "name": "search", "description": "Regex search in *.py files. Returns file:line: text.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string", "description": "subdirectory, default ."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "find_file", "description": "Find files whose path contains name (glob allowed).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read lines [start, end] with line numbers, max 200 lines.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "finish", "description": "Call when the fix is complete.",
        "parameters": {"type": "object", "properties": {}}}},
]
EXPLORE = {"search", "find_file", "read_file"}


def chat(model: str, messages: list, num_ctx: int) -> dict:
    """Return {"message": {...}, "prompt_eval_count": int, "eval_count": int}."""
    if v1.PROVIDER == "ollama":
        body = {"model": model, "messages": messages, "tools": TOOLS, "stream": False,
                "options": {"num_ctx": num_ctx, "temperature": 0, "num_predict": 4096}}
        req = urllib.request.Request(v1.OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=900))

    payload = {"model": model, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
               "temperature": 0, "max_tokens": 4096}
    headers = {"Authorization": f"Bearer {v1.get_openrouter_key()}", "Content-Type": "application/json",
               "HTTP-Referer": "https://theones.io", "X-Title": "SWE-bench JIT v2"}
    req = urllib.request.Request(v1.OPENROUTER_URL, data=json.dumps(payload).encode(), headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"OpenRouter HTTP {e.code}: {body}") from e
        if "choices" not in data:  # provider-side error wrapped in a 200
            if attempt < 4:
                time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"OpenRouter error payload: {json.dumps(data)[:500]}")
        usage = data.get("usage") or {}
        return {"message": data["choices"][0].get("message") or {},
                "prompt_eval_count": usage.get("prompt_tokens", 0),
                "eval_count": usage.get("completion_tokens", 0)}
    raise RuntimeError("OpenRouter failed after retries")


def native_calls(msg: dict) -> list[tuple[str | None, str, dict]]:
    """[(tool_call_id, name, args)] from native tool_calls."""
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        out.append((tc.get("id"), fn.get("name") or "", args if isinstance(args, dict) else {}))
    return out


def normalize_path_arg(repo_dir: Path, name: str, args: dict, tracked: list[str]) -> dict:
    """Resolve 'path' for search/read_file; a bad path becomes an explicit error, not '(no matches)'."""
    if name == "find_file" or not str(args.get("path") or "").strip():
        return args
    p, err = resolve_path(repo_dir, str(args["path"]), tracked)
    if p is None:
        return {**args, "_error": err}
    return {**args, "path": str(p.relative_to(repo_dir.resolve())) or "."}


def unique_match_in_read_files(repo_dir: Path, edit, touched: dict) -> Path | None:
    """Wrong path but SEARCH applies to exactly one file the model has read: use that file."""
    hits = []
    for rel in touched:
        p = repo_dir / rel
        if p.is_file():
            new_text, _ = apply_edit(p.read_text(encoding="utf-8"), edit)
            if new_text is not None:
                hits.append(p)
    return hits[0] if len(hits) == 1 else None


def run_edits(repo_dir: Path, content: str, stats: dict, touched: dict, tracked: list[str]) -> str | None:
    edits = parse_edits(content)
    if not edits:
        return None
    reports = []
    for e in edits:
        p, err = resolve_path(repo_dir, e.path, tracked)
        if p is None:
            p = unique_match_in_read_files(repo_dir, e, touched)
            if p is not None:
                stats["path_recovered"] = stats.get("path_recovered", 0) + 1
        if p is None or not p.is_file():
            stats["edits_failed"] += 1
            reports.append(f"EDIT FAILED {e.path}: {err or 'not a file'}")
            continue
        rel = str(p.relative_to(repo_dir.resolve()))
        before = p.read_text(encoding="utf-8")
        after, how = apply_edit(before, e)
        if after is None:
            stats["edits_failed"] += 1
            reports.append(f"EDIT FAILED {rel}: {how}")
            continue
        err = syntax_error(after) if p.suffix == ".py" else None
        if err:
            stats["edits_failed"] += 1
            stats["syntax_reverts"] += 1
            reports.append(f"EDIT REVERTED {rel}: result has invalid Python syntax ({err}). File unchanged.")
            continue
        p.write_text(after, encoding="utf-8")
        stats["edits_ok"] += 1
        stats["match_modes"][how] = stats["match_modes"].get(how, 0) + 1
        touched.setdefault(rel, {"ranges": set(), "patched": False})["patched"] = True
        warn = new_flakes(before, after) if p.suffix == ".py" else []
        checks = "syntax OK" + (f"; NEW pyflakes warnings: {warn}" if warn else "; no new pyflakes warnings")
        reports.append(f"EDIT OK {rel} (match: {how}). {checks}\nCurrent diff of {rel}:\n{diff_hunk(repo_dir, rel)}")
    return "\n\n".join(reports)


def solve(task: dict, model: str, max_turns: int, num_ctx: int, work: Path) -> dict:
    arm = "v2"
    repo_dir = work / f"{task['instance_id']}__{arm}"
    v1.checkout(task["repo"], task["base_commit"], repo_dir)
    issue = task["problem_statement"][:6000]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Repository: {task['repo']}\n\n<issue>\n{issue}\n</issue>\n\n"
                                            "Start by locating the relevant code."}]
    touched: dict = {}
    seen: dict = {}
    tracked = subprocess.run(["git", "ls-files"], cwd=repo_dir, capture_output=True,
                             text=True).stdout.splitlines()
    stats = {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0, "parse_failures": 0,
             "fallback_calls": 0, "tool_errors": 0, "repeat_calls": 0, "edits_ok": 0,
             "edits_failed": 0, "syntax_reverts": 0, "match_modes": {}, "finish_rejected": 0,
             "finished": False, "ctx_overflow": 0}
    t0 = time.time()
    for turn in range(1, max_turns + 1):
        stats["turns"] = turn
        ws = v1.working_set_block(repo_dir, touched)
        send = [{"role": "system", "content": SYSTEM + ("\n\n" + ws if ws else "")}] + messages[1:]
        try:
            r = chat(model, send, num_ctx)
        except Exception as e:
            stats["error"] = f"{type(e).__name__}: {e}"
            break
        stats["prompt_tokens"] += r.get("prompt_eval_count", 0) or 0
        stats["completion_tokens"] += r.get("eval_count", 0) or 0
        if (r.get("prompt_eval_count") or 0) >= num_ctx - 64:
            stats["ctx_overflow"] += 1
        msg = r.get("message") or {}
        content = msg.get("content") or ""
        calls = native_calls(msg)

        assistant = {"role": "assistant", "content": content}
        if msg.get("tool_calls"):
            assistant["tool_calls"] = msg["tool_calls"]
        messages.append(assistant)

        edit_report = run_edits(repo_dir, content, stats, touched, tracked)
        if not calls and edit_report is None:
            legacy = v1.parse_tool_call({"content": content})  # model wrote a call as text
            if legacy and legacy[0] in EXPLORE | {"finish"}:
                stats["fallback_calls"] += 1
                calls = [(None, legacy[0], legacy[1])]
        if not calls and edit_report is None:
            stats["parse_failures"] += 1
            messages.append({"role": "user", "content": "Nothing was executed. Call one of the functions "
                             "(search, find_file, read_file, finish) or write a SEARCH/REPLACE block."})
            continue

        feedback = [edit_report] if edit_report else []
        done = False
        for idx, (call_id, name, args) in enumerate(calls):
            if idx > 0:
                out = "Skipped: one function call per turn."
            elif name == "finish":
                edit_failed_now = bool(edit_report) and "EDIT OK" not in edit_report
                if edit_failed_now or (not v1.git_diff(repo_dir).strip() and stats["finish_rejected"] < 2):
                    stats["finish_rejected"] += 1
                    out = ("Rejected: your edit in this message failed (see above); fix it before finishing."
                           if edit_failed_now else
                           "Rejected: no file has been changed yet. Write a SEARCH/REPLACE block first.")
                else:
                    stats["finished"] = done = True
                    out = "FINISHED"
            elif name in EXPLORE:
                args = normalize_path_arg(repo_dir, name, args, tracked)
                sig = json.dumps([name, args], sort_keys=True, default=str)
                seen[sig] = seen.get(sig, 0) + 1
                if seen[sig] > 1 and name == "read_file":
                    stats["repeat_calls"] += 1  # older copy may be aged out of history: show it again
                    out = "(repeated call, same result as before)\n" + v1.run_tool(repo_dir, name, args)
                elif seen[sig] > 1:
                    stats["repeat_calls"] += 1
                    out = ("LOOP GUARD: you already made this exact call; its result is above. "
                           "Use the WORKING_SET line map, read a different range, or edit now.")
                elif args.get("_error"):
                    out = f"ERROR: {args['_error']}"
                else:
                    out = v1.run_tool(repo_dir, name, args)
                    if name == "read_file" and args.get("path"):
                        info = touched.setdefault(str(args["path"]), {"ranges": set(), "patched": False})
                        info["ranges"].add((int(args.get("start") or 1), int(args.get("end") or 0)))
            else:
                out = f"ERROR: unknown function {name}. To edit, write a SEARCH/REPLACE block."
            if out.startswith("ERROR"):
                stats["tool_errors"] += 1
            out = v1.cap(out, 6000)
            if call_id is not None:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": out})
            else:
                feedback.append(f"[{name} result]\n{out}")
        if feedback:
            messages.append({"role": "user", "content": "\n\n".join(feedback)})
        for m in messages[2:-6]:  # same aging policy as the v1 jit arm
            if m["role"] in ("user", "tool") and len(m.get("content") or "") > 800:
                m["content"] = v1.cap(m["content"], 800)
        if done:
            break
    stats["wall_s"] = round(time.time() - t0, 1)
    trace_dir = work / "traces"
    trace_dir.mkdir(exist_ok=True)
    (trace_dir / f"{task['instance_id']}__{arm}.json").write_text(json.dumps(messages, ensure_ascii=False, indent=1))
    patch = v1.git_diff(repo_dir)
    stats["patch_lines"] = patch.count("\n")
    return {"patch": patch, "stats": stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--ids", required=True, help="comma-separated instance ids or a file path")
    ap.add_argument("--model", default="qwen/qwen-2.5-7b-instruct")
    ap.add_argument("--provider", default="auto", choices=["auto", "openrouter", "ollama"])
    ap.add_argument("--ollama", default="http://127.0.0.1:11434/api/chat")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default=str(Path.home() / ".hermes/cache/scratch/swe_work"))
    a = ap.parse_args()
    v1.PROVIDER = a.provider if a.provider != "auto" else ("openrouter" if "/" in a.model else "ollama")
    v1.OLLAMA = a.ollama if a.ollama.endswith("/api/chat") else f"{a.ollama.rstrip('/')}/api/chat"

    import pyarrow.parquet as pq
    rows = {r["instance_id"]: r for r in pq.read_table(a.dataset).to_pylist()}
    raw_ids = Path(a.ids).read_text() if Path(a.ids).is_file() else a.ids
    ids = [i.strip() for i in raw_ids.replace("\n", ",").split(",") if i.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    preds, tele = out / "preds_v2.jsonl", out / "telemetry_v2.jsonl"
    done = {json.loads(l)["instance_id"] for l in preds.read_text().splitlines()} if preds.exists() else set()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    for iid in ids:
        if iid in done:
            continue
        res = solve(rows[iid], a.model, a.max_turns, a.num_ctx, work)
        s = res["stats"]
        with preds.open("a") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": f"{a.model}__v2",
                                "model_patch": res["patch"]}) + "\n")
        with tele.open("a") as f:
            f.write(json.dumps({"instance_id": iid, "arm": "v2", **s}) + "\n")
        print(f"[v2] {iid}: turns={s['turns']} wall={s['wall_s']}s ptok={s['prompt_tokens']} "
              f"edits_ok={s['edits_ok']} edits_failed={s['edits_failed']} parse_fail={s['parse_failures']} "
              f"fallback={s['fallback_calls']} finished={s['finished']} diff_lines={s['patch_lines']}"
              + (f" ERROR={s['error'][:160]}" if s.get("error") else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
