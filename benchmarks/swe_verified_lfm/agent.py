#!/usr/bin/env python3
"""SWE-bench Verified agent loop for local Ollama models: BARE vs JIT arm.

Both arms share the model, tools, turn budget, temperature and tool-call parser.
The only difference is context engineering:
  bare: full tool outputs appended to history, no loop guard, no working set.
  jit : tool outputs capped per turn (older turns shrunk harder), loop guard on
        repeated calls, and a compact working-set block (touched files + AST
        symbol map with line numbers) refreshed into the system prompt.

Output: predictions JSONL in the official SWE-bench format
  {"instance_id", "model_name_or_path", "model_patch"}
plus a per-instance telemetry JSONL. Grading is done by the official
swebench harness (run_evaluation) in Docker, not by this script.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434/api/chat"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = ""
PROVIDER = "ollama"
REPO_CACHE = Path.home() / ".hermes/cache/swe_repos"

def get_openrouter_key() -> str:
    global API_KEY
    if API_KEY:
        return API_KEY
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        API_KEY = key
        return key
    env_file = Path.home() / ".hermes/.env"
    if env_file.exists():
        text = env_file.read_text()
        for var in ["JEV_OPENROUTER_KEY", "OPENROUTER_API_KEY"]:
            m = re.search(rf"^{var}=[\"']?(.*?)[\"']?$", text, re.M)
            if m and m.group(1):
                API_KEY = m.group(1).strip()
                return API_KEY
    return ""

SYSTEM = """You are a software engineer fixing a GitHub issue in a Python repository.
The repository root is the current directory; use repo-relative paths like 'pkg/module.py'.
You cannot run code, shell commands or tests. Only the tools below exist.

Reply with exactly ONE tool call and nothing else, in this format:
<|tool_call_start|>[read_file(path='pkg/module.py', start=100, end=160)]<|tool_call_end|>

Tools:
- search(pattern, path=".")          regex search in *.py files, returns file:line: text
- find_file(name)                    find files whose path contains name (glob like *.py allowed)
- read_file(path, start=1, end=None) read lines [start, end] with line numbers (max 200 lines)
- patch(path, old_string, new_string) replace an exact unique snippet in a file
- finish()                           call when the fix is complete

Workflow: locate the relevant code, read it, apply a minimal fix with patch, then finish.
Do not modify test files. old_string must match the file exactly, including indentation."""

TOOL_NAMES = {"search", "find_file", "read_file", "patch", "finish"}


# ---------------------------------------------------------------- repo setup
def checkout(repo: str, commit: str, dest: Path) -> None:
    mirror = REPO_CACHE / repo.replace("/", "__")
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--bare", f"https://github.com/{repo}.git", str(mirror)], check=True)
    if dest.exists():
        subprocess.run(["rm", "-rf", str(dest)], check=True)
    subprocess.run(["git", "clone", "-q", "--shared", str(mirror), str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", commit], check=True)


def git_diff(repo_dir: Path) -> str:
    return subprocess.run(["git", "-C", str(repo_dir), "diff"], capture_output=True, text=True).stdout


# ---------------------------------------------------------------- tools
def _safe(repo_dir: Path, rel: str) -> Path:
    """Resolve a model-supplied path inside the repo.

    Small models often emit '/pkg/mod.py' or '/<repo-name>/pkg/mod.py'; treat a leading
    slash as repo-relative and strip a leading repo-name segment when it does not exist.
    """
    rel = rel.strip().lstrip("/")
    if rel.startswith("./"):
        rel = rel[2:]
    first, _, rest = rel.partition("/")
    if rest and not (repo_dir / first).exists() and (repo_dir / rest).exists():
        rel = rest
    p = (repo_dir / rel).resolve()
    if not str(p).startswith(str(repo_dir.resolve())):
        raise ValueError("path outside repository")
    return p


def run_tool(repo_dir: Path, name: str, args: dict) -> str:
    try:
        if name == "search":
            pat = str(args.get("pattern", ""))
            sub = str(args.get("path", ".") or ".")
            sub = "." if sub in {"", ".", "/", "./"} else str(_safe(repo_dir, sub).relative_to(repo_dir.resolve()))
            r = subprocess.run(["rg", "-n", "--no-heading", "-g", "*.py", "-e", pat, sub],
                               cwd=repo_dir, capture_output=True, text=True, timeout=30)
            out = r.stdout.strip() or "(no matches)"
            lines = out.splitlines()
            return "\n".join(lines[:400]) + (f"\n... ({len(lines)} matches total)" if len(lines) > 400 else "")
        if name == "find_file":
            q = str(args.get("name", "") or args.get("pattern", ""))
            files = subprocess.run(["git", "ls-files"], cwd=repo_dir, capture_output=True, text=True).stdout.splitlines()
            if any(c in q for c in "*?["):
                import fnmatch
                hits = [f for f in files if fnmatch.fnmatch(f, q) or fnmatch.fnmatch(Path(f).name, q)]
            else:
                hits = [f for f in files if q and q in f]
            more = f"\n... ({len(hits)} files total, narrow the name)" if len(hits) > 100 else ""
            return "\n".join(hits[:100]) + more if hits else "(no files)"
        if name == "read_file":
            p = _safe(repo_dir, str(args.get("path", "")))
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, int(args.get("start") or 1))
            end = int(args.get("end") or start + 199)
            end = min(end, start + 199, len(lines))
            body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
            return f"{args.get('path')} ({len(lines)} lines total)\n{body}"
        if name == "patch":
            p = _safe(repo_dir, str(args.get("path", "")))
            old = str(args.get("old_string", "") or args.get("old", ""))
            new = str(args.get("new_string", "") or args.get("new", ""))
            text = p.read_text(encoding="utf-8")
            n = text.count(old) if old else 0
            if n != 1:
                return f"ERROR: old_string found {n} times (must be exactly 1). Re-read the file and copy it exactly."
            new_text = text.replace(old, new, 1)
            if p.suffix == ".py":
                try:
                    ast.parse(new_text, filename=str(p))
                except SyntaxError as se:
                    return f"ERROR: patch creates invalid Python syntax at line {se.lineno}: {se.msg}. Reverted. Check brackets/indentation and re-apply."
            p.write_text(new_text, encoding="utf-8")
            return f"OK: patched {args.get('path')}"
        if name == "finish":
            return "FINISHED"
        return f"ERROR: unknown tool {name}"
    except Exception as e:  # tool errors are shown to the model, both arms alike
        return f"ERROR: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- parsing
def _balanced_objects(text: str):
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]


def _escape_newlines_in_strings(src: str) -> str:
    """Escape raw newlines/tabs inside single-line string literals so ast can parse them."""
    out, quote, esc, i = [], None, False, 0
    while i < len(src):
        ch = src[i]
        if quote is None:
            if src.startswith(('"""', "'''"), i):
                end = src.find(src[i:i + 3], i + 3)
                end = len(src) if end == -1 else end + 3
                out.append(src[i:end])
                i = end
                continue
            if ch in "'\"":
                quote = ch
            out.append(ch)
        else:
            if esc:
                esc = False
                out.append(ch)
            elif ch == "\\":
                esc = True
                out.append(ch)
            elif ch == quote:
                quote = None
                out.append(ch)
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def _parse_pythonic_call(content: str):
    """Parse LFM-native calls: <|tool_call_start|>[fn(a='x', b=1)]<|tool_call_end|>."""
    m = re.search(r"<\|tool_call_start\|>(.*?)(?:<\|tool_call_end\|>|$)", content, re.S)
    if not m:
        return None
    src = m.group(1).strip()
    try:
        node = ast.parse(src, mode="eval").body
    except SyntaxError:
        try:
            node = ast.parse(_escape_newlines_in_strings(src), mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.List) and node.elts:
        node = node.elts[0]
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in TOOL_NAMES):
        return None
    args = {}
    for kw in node.keywords:
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except ValueError:
            return None
    return node.func.id, args


def parse_tool_call(msg: dict):
    """Return (name, args) or None. Native tool_calls first, then JSON in content."""
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        a = fn.get("arguments")
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except ValueError:
                a = {}
        return fn.get("name"), a or {}
    content = msg.get("content") or ""
    pythonic = _parse_pythonic_call(content)
    if pythonic:
        return pythonic
    for blob in _balanced_objects(content):
        try:
            obj = json.loads(blob)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("name") in TOOL_NAMES:
            a = obj.get("arguments") or obj.get("parameters") or {}
            return obj["name"], a if isinstance(a, dict) else {}
    m = re.search(r"\b(search|find_file|read_file|patch|finish)\((.*?)\)", content, re.S)
    if m and m.group(1) == "finish":
        return "finish", {}
    return None


# ---------------------------------------------------------------- JIT pieces
def ast_symbols(path: Path, limit: int = 40) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {node.name} L{node.lineno}-{node.end_lineno}")
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name} L{node.lineno}-{node.end_lineno}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(f"  .{sub.name} L{sub.lineno}-{sub.end_lineno}")
    return out[:limit]


def working_set_block(repo_dir: Path, touched: dict) -> str:
    if not touched:
        return ""
    parts = ["<WORKING_SET> files you already inspected (use line ranges instead of re-reading whole files):"]
    for rel, info in list(touched.items())[-6:]:
        p = repo_dir / rel
        syms = ast_symbols(p) if p.exists() else []
        parts.append(f"@ref:{rel} read={sorted(info['ranges'])[-4:]} patched={info['patched']}")
        parts.extend(f"    {s}" for s in syms)
    parts.append("</WORKING_SET>")
    return "\n".join(parts)


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.2):]
    return f"{head}\n...[{len(text) - len(head) - len(tail)} chars trimmed by JIT; narrow your query or line range]...\n{tail}"


# ---------------------------------------------------------------- loop
def chat(model: str, messages: list, num_ctx: int) -> dict:
    if PROVIDER == "ollama":
        body = {"model": model, "messages": messages, "stream": False,
                "options": {"num_ctx": num_ctx, "temperature": 0, "num_predict": 8192}}
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=600))

    key = get_openrouter_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://theones.io",
        "X-Title": "SWE-bench JIT"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096
    }
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(payload).encode(), headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                usage = data.get("usage", {})
                choice = data.get("choices", [{}])[0]
                return {
                    "message": choice.get("message", {}),
                    "prompt_eval_count": usage.get("prompt_tokens", 0),
                    "eval_count": usage.get("completion_tokens", 0)
                }
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode()
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"OpenRouter HTTP {e.code}: {e.reason} - {err_body}")
    raise RuntimeError("OpenRouter failed after retries")


def solve(task: dict, arm: str, model: str, max_turns: int, num_ctx: int, work: Path) -> dict:
    repo_dir = work / f"{task['instance_id']}__{arm}"
    checkout(task["repo"], task["base_commit"], repo_dir)
    issue = task["problem_statement"]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Repository: {task['repo']}\n\n<issue>\n{issue}\n</issue>\n\nStart by locating the relevant code."}]
    touched: dict = {}
    seen_calls: dict = {}
    stats = {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0, "parse_failures": 0,
             "tool_errors": 0, "repeat_calls": 0, "patches_ok": 0, "finished": False, "ctx_overflow": 0}
    t0 = time.time()
    for turn in range(1, max_turns + 1):
        stats["turns"] = turn
        send = messages
        if arm == "jit":
            ws = working_set_block(repo_dir, touched)
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
        msg = r.get("message", {})
        messages.append({"role": "assistant", "content": msg.get("content") or json.dumps(
            {"tool_calls": msg.get("tool_calls")}, ensure_ascii=False)})
        call = parse_tool_call(msg)
        if not call:
            stats["parse_failures"] += 1
            messages.append({"role": "user", "content": "No tool call found, nothing was executed. There is no shell and "
                             "no JSON plan format. Reply with ONLY one call, e.g. "
                             "<|tool_call_start|>[search(pattern='def my_func')]<|tool_call_end|>"})
            continue
        name, args = call
        sig = json.dumps([name, args], sort_keys=True, default=str)
        seen_calls[sig] = seen_calls.get(sig, 0) + 1
        if seen_calls[sig] > 1 and name != "patch":
            stats["repeat_calls"] += 1
        if arm == "jit" and seen_calls[sig] > 1 and name in {"search", "find_file", "read_file"}:
            out = ("LOOP GUARD: you already made this exact call; its result is above. "
                   "Use the WORKING_SET line map, read a different range, or apply the patch now.")
        else:
            out = run_tool(repo_dir, name, args)
        if out.startswith("ERROR"):
            stats["tool_errors"] += 1
        if name == "patch" and out.startswith("OK"):
            stats["patches_ok"] += 1
        if name in {"read_file", "patch"} and args.get("path"):
            info = touched.setdefault(str(args["path"]), {"ranges": set(), "patched": False})
            if name == "read_file":
                info["ranges"].add((int(args.get("start") or 1), int(args.get("end") or 0)))
            elif out.startswith("OK"):
                info["patched"] = True
        if name == "finish":
            stats["finished"] = True
            break
        if arm == "jit":
            out = cap(out, 6000)
            # shrink older tool observations, keep the last 6 messages intact
            for m in messages[2:-6]:
                if m["role"] == "user" and m["content"].startswith("[tool") and len(m["content"]) > 800:
                    m["content"] = cap(m["content"], 800)
        messages.append({"role": "user", "content": f"[tool {name} result]\n{out}"})
    stats["wall_s"] = round(time.time() - t0, 1)
    trace_dir = work / "traces"
    trace_dir.mkdir(exist_ok=True)
    (trace_dir / f"{task['instance_id']}__{arm}.json").write_text(json.dumps(messages, ensure_ascii=False, indent=1))
    patch = git_diff(repo_dir)
    stats["patch_lines"] = patch.count("\n")
    return {"patch": patch, "stats": stats}


def main() -> int:
    global OLLAMA, PROVIDER, API_KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--ids", required=True, help="comma-separated instance ids")
    ap.add_argument("--arm", choices=["bare", "jit"], required=True)
    ap.add_argument("--model", default="qwen/qwen-2.5-7b-instruct")
    ap.add_argument("--provider", default="auto", choices=["auto", "openrouter", "ollama"])
    ap.add_argument("--api-key", default="")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_API", "http://127.0.0.1:11434/api/chat"))
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default=str(Path.home() / ".hermes/cache/scratch/swe_work"))
    a = ap.parse_args()
    if a.api_key:
        API_KEY = a.api_key
    if a.provider == "auto":
        PROVIDER = "openrouter" if ("/" in a.model or "openrouter" in a.model) else "ollama"
    else:
        PROVIDER = a.provider
    OLLAMA = a.ollama if a.ollama.endswith("/api/chat") else f"{a.ollama.rstrip('/')}/api/chat"

    import pyarrow.parquet as pq
    rows = {r["instance_id"]: r for r in pq.read_table(a.dataset).to_pylist()}
    ids = [i.strip() for i in a.ids.split(",") if i.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    preds = out / f"preds_{a.arm}.jsonl"
    tele = out / f"telemetry_{a.arm}.jsonl"
    done = {json.loads(l)["instance_id"] for l in preds.read_text().splitlines()} if preds.exists() else set()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    for iid in ids:
        if iid in done:
            continue
        res = solve(rows[iid], a.arm, a.model, a.max_turns, a.num_ctx, work)
        with preds.open("a") as f:
            f.write(json.dumps({"instance_id": iid, "model_name_or_path": f"{a.model}__{a.arm}",
                                "model_patch": res["patch"]}) + "\n")
        with tele.open("a") as f:
            f.write(json.dumps({"instance_id": iid, "arm": a.arm, **res["stats"]}) + "\n")
        s = res["stats"]
        print(f"[{a.arm}] {iid}: turns={s['turns']} wall={s['wall_s']}s ptok={s['prompt_tokens']} "
              f"patches_ok={s['patches_ok']} parse_fail={s['parse_failures']} finished={s['finished']} "
              f"diff_lines={s['patch_lines']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
