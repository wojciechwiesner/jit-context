#!/usr/bin/env python3
"""
Real Multi-Turn Agentic SWE Benchmark: JIT vs RAW.
Agent is placed in a multi-file repo with only the issue text.
Available Tools:
  - search_files(pattern)
  - read_file(path, offset, limit)
  - patch(path, old_string, new_string)
  - run_tests()
Verification: pytest exit_code == 0.
Measures: Turns, Total Wall Time, Total Tokens, Tool Calls, Discovery Tax.
"""

import os
import sys
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ENV_PATH = Path.home() / ".hermes" / ".env"
GOOGLE_API_KEY = None
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("GOOGLE_API_KEY="):
            GOOGLE_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

if not GOOGLE_API_KEY:
    print("ERROR: GOOGLE_API_KEY not found in ~/.hermes/.env", file=sys.stderr)
    sys.exit(1)

def setup_django_repo(base_dir: Path):
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)

    # Multi-file directory tree mimicking Django
    (base_dir / "django/contrib/auth").mkdir(parents=True)
    (base_dir / "django/core").mkdir(parents=True)
    (base_dir / "django/utils").mkdir(parents=True)
    (base_dir / "tests/auth_tests").mkdir(parents=True)

    # Decoy files
    (base_dir / "django/core/validators.py").write_text("""# Core validators
class BaseValidator:
    pass
def validate_slug(value):
    pass
""")
    (base_dir / "django/contrib/auth/models.py").write_text("""# Auth models
class User:
    username = ""
""")
    (base_dir / "django/contrib/auth/forms.py").write_text("""# Auth forms
class UserCreationForm:
    pass
""")

    # Target file
    (base_dir / "django/contrib/auth/validators.py").write_text("""import re

class RegexValidator:
    regex = ""
    message = "Enter a valid value."
    def __init__(self, regex=None, message=None):
        if regex is not None: self.regex = regex
        if message is not None: self.message = message
        self.compiled_regex = re.compile(self.regex)

    def __call__(self, value):
        if not self.compiled_regex.search(str(value)):
            raise ValueError(self.message)

class ASCIIUsernameValidator(RegexValidator):
    regex = r"^[\\w.@+-]+$"
    message = "Enter a valid username."

class UnicodeUsernameValidator(RegexValidator):
    regex = r"^[\\w.@+-]+$"
    message = "Enter a valid username."
""")

    # Test file
    (base_dir / "tests/auth_tests/test_validators.py").write_text("""import pytest
from django.contrib.auth.validators import ASCIIUsernameValidator, UnicodeUsernameValidator

def test_ascii_validator_rejects_trailing_newline():
    v = ASCIIUsernameValidator()
    v("valid_user")
    with pytest.raises(ValueError):
        v("user\\n")

def test_unicode_validator_rejects_trailing_newline():
    v = UnicodeUsernameValidator()
    v("valid_user")
    with pytest.raises(ValueError):
        v("user\\n")
""")


def execute_agent_loop(mode: str, repo_dir: Path, issue_text: str, max_turns: int = 8):
    print(f"\n=======================================================")
    print(f" 🚀 STARTING AGENTIC RUN: {mode.upper()}")
    print(f"=======================================================")

    sys_instructions = """You are an autonomous SWE agent solving a bug in a repository.
You have the following tools available:
1. {"tool": "search_files", "pattern": "string to search"} -> returns matching files and lines
2. {"tool": "read_file", "path": "path/to/file", "offset": 1, "limit": 50} -> reads file with line numbers
3. {"tool": "patch", "path": "path/to/file", "old_string": "exact text", "new_string": "replacement"} -> edits file
4. {"tool": "run_tests"} -> executes pytest on the test suite
5. {"tool": "done", "summary": "explanation of fix"} -> call this when tests pass and task is complete

Every turn, you MUST output ONLY ONE JSON tool call.
"""

    if mode == "jit":
        # JIT injects <ONA_CONTEXT> with L1 AST target pointer
        capsule = """<ONA_CONTEXT scope="django" epoch="1" confidence="1.00" complexity="direct_fix">
  [DEV RUNTIME & AST WORKING SET]
    • Target Symbol: ASCIIUsernameValidator, UnicodeUsernameValidator
    • Ref Pointer: @ref:django/contrib/auth/validators.py:16
  [ACTIVE INVARIANTS]
    • ZERO FAKE: run_tests must return exit code 0.
</ONA_CONTEXT>
"""
        initial_prompt = f"{capsule}\nIssue:\n{issue_text}\n\nStart investigating and solving this issue."
    else:
        initial_prompt = f"Issue:\n{issue_text}\n\nStart investigating and solving this issue."

    messages = [
        {"role": "user", "parts": [{"text": sys_instructions + "\n\n" + initial_prompt}]}
    ]

    total_tokens = 0
    t0 = time.time()
    turn = 0
    discovery_tax = 0
    task_passed = False

    while turn < max_turns:
        turn += 1
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GOOGLE_API_KEY}"
        payload = {
            "contents": messages,
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                usage = data.get("usageMetadata", {})
                total_tokens += usage.get("totalTokenCount", 0)
                tool_call = json.loads(text)
        except Exception as e:
            print(f"  [Turn {turn}] API Error: {e}")
            break

        tool_name = tool_call.get("tool")
        print(f"  [Turn {turn}] Tool: {tool_name}({ {k:v for k,v in tool_call.items() if k != 'tool'} })")

        # Execute tool in real repo environment
        tool_output = ""
        if tool_name == "search_files":
            discovery_tax += 1
            pat = tool_call.get("pattern", "")
            matches = []
            for root, _, files in os.walk(repo_dir):
                for f in files:
                    if f.endswith(".py"):
                        p = Path(root) / f
                        try:
                            for idx, line in enumerate(p.read_text().splitlines(), 1):
                                if pat.lower() in line.lower():
                                    matches.append(f"{p.relative_to(repo_dir)}:{idx}: {line.strip()}")
                        except Exception:
                            pass
            tool_output = "\n".join(matches[:20]) if matches else "No matches found."

        elif tool_name == "read_file":
            discovery_tax += 1
            rel_path = tool_call.get("path", "")
            target_p = repo_dir / rel_path
            if not target_p.exists():
                tool_output = f"Error: File '{rel_path}' not found."
            else:
                lines = target_p.read_text().splitlines()
                off = max(1, tool_call.get("offset", 1))
                lim = tool_call.get("limit", 50)
                slice_lines = lines[off-1:off-1+lim]
                tool_output = "\n".join(f"{off+i:3d}| {l}" for i, l in enumerate(slice_lines))

        elif tool_name == "patch":
            rel_path = tool_call.get("path", "")
            target_p = repo_dir / rel_path
            if not target_p.exists():
                tool_output = f"Error: File '{rel_path}' not found."
            else:
                content = target_p.read_text()
                old_s = tool_call.get("old_string", "")
                new_s = tool_call.get("new_string", "")
                if old_s not in content:
                    tool_output = f"Error: old_string not found in '{rel_path}'."
                else:
                    target_p.write_text(content.replace(old_s, new_s, 1))
                    tool_output = f"Successfully patched '{rel_path}'."

        elif tool_name == "run_tests":
            res = subprocess.run(
                ["pytest", "tests/auth_tests/test_validators.py"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(repo_dir)}
            )
            if res.returncode == 0:
                tool_output = f"PYTEST PASSED (exit code 0):\n{res.stdout[-300:]}"
                task_passed = True
            else:
                tool_output = f"PYTEST FAILED (exit code {res.returncode}):\n{res.stdout[-400:]}"

        elif tool_name == "done":
            print(f"  [Agent Concluded]: {tool_call.get('summary')}")
            break

        print(f"    -> Result ({len(tool_output)} chars): {tool_output.splitlines()[0] if tool_output else 'empty'}")

        messages.append({"role": "model", "parts": [{"text": text}]})
        messages.append({"role": "user", "parts": [{"text": f"Tool Result:\n{tool_output}\n\nNext tool call:"}]})

    elapsed = round(time.time() - t0, 2)
    print(f"\n>>> RUN FINISHED in {elapsed}s | Turns: {turn} | Discovery Ops: {discovery_tax} | Tokens: {total_tokens} | Passed: {task_passed} <<<")
    return {
        "mode": mode,
        "elapsed_s": elapsed,
        "turns": turn,
        "discovery_ops": discovery_tax,
        "tokens": total_tokens,
        "passed": task_passed
    }


issue = """UsernameValidator allows trailing newline in usernames
Description:
ASCIIUsernameValidator and UnicodeUsernameValidator use the regex r'^[\\w.@+-]+$'
In Python regexes $ will also match a trailing newline. Therefore, the user name validators will accept usernames which end with a newline.
You can avoid this behavior by instead using \\A and \\Z to terminate regexes. Change regex to r'\\A[\\w.@+-]+\\Z' in contrib.auth.validators."""

# Run RAW Agentic
raw_dir = Path("/tmp/agentic_repo_raw")
setup_django_repo(raw_dir)
raw_stats = execute_agent_loop("raw", raw_dir, issue)

# Run JIT Agentic
jit_dir = Path("/tmp/agentic_repo_jit")
setup_django_repo(jit_dir)
jit_stats = execute_agent_loop("jit", jit_dir, issue)

print("\n==================================================================")
print(" 📊 FINAL AGENTIC SWE BATTLE RESULTS")
print("==================================================================")
print(f"RAW Mode:  {raw_stats['turns']} turns | {raw_stats['elapsed_s']}s | {raw_stats['tokens']:,} tokens | Discovery ops: {raw_stats['discovery_ops']} | Passed: {raw_stats['passed']}")
print(f"JIT Mode:  {jit_stats['turns']} turns | {jit_stats['elapsed_s']}s | {jit_stats['tokens']:,} tokens | Discovery ops: {jit_stats['discovery_ops']} | Passed: {jit_stats['passed']}")
delta_tokens = round((jit_stats['tokens'] - raw_stats['tokens']) / raw_stats['tokens'] * 100, 1)
delta_time = round((jit_stats['elapsed_s'] - raw_stats['elapsed_s']) / raw_stats['elapsed_s'] * 100, 1)
print(f"⚡ JIT ADVANTAGE: {delta_tokens}% tokens, {delta_time}% time, -{raw_stats['discovery_ops'] - jit_stats['discovery_ops']} discovery tool hops")
print("==================================================================")
