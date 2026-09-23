#!/usr/bin/env python3
"""
Honest SWE Benchmark: 5 Real Python Tasks with Deterministic Pytest Verification.
Zero regex guessing, zero placeholder diffs.
Flow:
  1. Setup task source & test in isolated directory
  2. Run baseline pytest -> MUST FAIL (confirms test validity)
  3. Generate JIT Context Capsule (<ONA_CONTEXT>) with AST line numbers
  4. Prompt model (Gemini 3.8 Flash) for surgical tool patch
  5. Apply patch to file on disk
  6. Run post-patch pytest -> exit code 0 = VERIFIED PASS, else FAIL
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

TASKS_BASE = Path("/tmp/honest_swe_5")
if TASKS_BASE.exists():
    shutil.rmtree(TASKS_BASE)
TASKS_BASE.mkdir(parents=True)

# -------------------------------------------------------------------------
# Task Definitions
# -------------------------------------------------------------------------
TASKS = [
    {
        "id": "django__django-11099",
        "title": "UsernameValidator allows trailing newline in usernames",
        "description": "ASCIIUsernameValidator and UnicodeUsernameValidator use regex r'^[\\w.@+-]+$'. In Python regex, $ matches before a trailing newline. Use \\Z instead of $ so usernames ending with \\n are rejected.",
        "file": "validators.py",
        "code": """import re

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
""",
        "test": """import pytest
from validators import ASCIIUsernameValidator, UnicodeUsernameValidator

def test_ascii_validator():
    v = ASCIIUsernameValidator()
    v("valid_user")
    with pytest.raises(ValueError):
        v("user\\n")

def test_unicode_validator():
    v = UnicodeUsernameValidator()
    v("valid_user")
    with pytest.raises(ValueError):
        v("user\\n")
"""
    },
    {
        "id": "django__django-11848",
        "title": "parse_http_date two digit year check RFC 7231",
        "description": "RFC 7231 specifies that 2-digit years more than 50 years in the future must be interpreted as past century. Instead of hardcoded year < 70, compare to current_year: if year - (current_year % 100) > 50 -> year += current_century - 100, else year += current_century.",
        "file": "http_date.py",
        "code": """import re, datetime

def parse_http_date(date_str):
    m = re.match(r"^([0-9]{2})$", date_str)
    if not m:
        raise ValueError("Invalid format")
    year = int(m.group(1))
    if year < 100:
        if year < 70:
            year += 2000
        else:
            year += 1900
    return year
""",
        "test": """import pytest, datetime
from http_date import parse_http_date

def test_rfc7231_year():
    # Year 71 in 2026 is 45 years in future (<= 50) -> MUST be 2071, NOT 1971
    assert parse_http_date("71") == 2071
"""
    },
    {
        "id": "django__django-14382",
        "title": "django-admin startapp with trailing slash results in empty app directory",
        "description": "Calling os.path.basename() on a target with trailing slash (e.g. 'myapp/') returns empty string '', causing CommandError. Strip trailing slashes or run validate_name on abspath/clean path.",
        "file": "templates.py",
        "code": """import os

class CommandError(Exception):
    pass

class TemplateCommand:
    def validate_name(self, name, app_or_project):
        if not name:
            raise CommandError(f"'' is not a valid {app_or_project} name.")

    def handle(self, app_or_project, name, target=None):
        if app_or_project == 'app':
            self.validate_name(os.path.basename(target), 'app')
        top_dir = os.path.abspath(os.path.expanduser(target))
        return f"Created {name} in {top_dir}"
""",
        "test": """import pytest
from templates import TemplateCommand, CommandError

def test_trailing_slash_target():
    cmd = TemplateCommand()
    # Target has trailing slash 'myapp/'
    res = cmd.handle('app', 'myapp', target='myapp/')
    assert "Created myapp" in res
"""
    },
    {
        "id": "django__django-15400",
        "title": "SimpleLazyObject doesn't implement __radd__",
        "description": "SimpleLazyObject missing __radd__. Implement __radd__(self, other) to return other + self._wrapped (or other + self).",
        "file": "functional.py",
        "code": """class SimpleLazyObject:
    def __init__(self, func):
        self._setupfunc = func
        self._wrapped = None

    def _setup(self):
        self._wrapped = self._setupfunc()

    def __add__(self, other):
        if self._wrapped is None:
            self._setup()
        return self._wrapped + other
""",
        "test": """import pytest
from functional import SimpleLazyObject

def test_radd():
    lazy = SimpleLazyObject(lambda: 5)
    # other + lazy invokes lazy.__radd__(other)
    assert 10 + lazy == 15
"""
    },
    {
        "id": "astropy__astropy-14995",
        "title": "NDDataRef mask propagation fails when operand has no mask",
        "description": "When operand does not have a mask (operand.mask is None), _arithmetic_mask should return copy of self.mask instead of failing. Change 'elif operand is None:' to 'elif operand.mask is None:'.",
        "file": "ndarithmetic.py",
        "code": """import copy

class MockOperand:
    def __init__(self, mask=None):
        self.mask = mask

class NDArithmetic:
    def __init__(self, mask=None):
        self.mask = mask

    def _arithmetic_mask(self, operand, handle_mask):
        if self.mask is None and operand is not None:
            return copy.deepcopy(operand.mask)
        elif operand is None:
            return copy.deepcopy(self.mask)
        else:
            return handle_mask(self.mask, operand.mask)
""",
        "test": """import pytest
from ndarithmetic import NDArithmetic, MockOperand

def test_mask_when_operand_mask_is_none():
    obj = NDArithmetic(mask=[1, 0, 1])
    operand = MockOperand(mask=None)
    # handle_mask would fail if called with None
    res = obj._arithmetic_mask(operand, handle_mask=lambda a, b: [x | y for x, y in zip(a, b)])
    assert res == [1, 0, 1]
"""
    }
]

# -------------------------------------------------------------------------
# Benchmark Runner
# -------------------------------------------------------------------------
print("==================================================================")
print(" 🔬 HONEST SWE BENCHMARK (5 Verified Real Tasks, 100% Pytest)")
print("==================================================================")

results = []

for idx, task in enumerate(TASKS, 1):
    tid = task["id"]
    tdir = TASKS_BASE / tid
    tdir.mkdir(parents=True, exist_ok=True)

    src_file = tdir / task["file"]
    test_file = tdir / f"test_{task['file']}"

    src_file.write_text(task["code"])
    test_file.write_text(task["test"])

    # 1. Verify baseline test fails
    base_res = subprocess.run(["pytest", str(test_file)], capture_output=True, text=True)
    if base_res.returncode == 0:
        print(f"[{idx}/5] {tid} -> INVALID BASELINE: test passed before fix! Aborting.")
        continue

    # Number lines for AST working set
    numbered_lines = "\n".join(f"{i+1:3d}| {line}" for i, line in enumerate(task["code"].splitlines()))

    # 2. Assemble JIT Context Capsule
    capsule = f"""<ONA_CONTEXT scope="{tid.split('__')[0]}" epoch="1" confidence="1.00" complexity="direct_fix">
  [DEV RUNTIME & AST WORKING SET]
    • Target File: {task['file']}
    • Working Set (Lines & Code):
{numbered_lines}
  [ACTIVE INVARIANTS]
    • ZERO FAKE / REAL RUNTIME: Your fix is directly verified via pytest execution.
    • RETURN FORMAT: Return ONLY valid JSON:
      {{"tool": "patch", "old_string": "exact unique text to replace", "new_string": "replacement text"}}
</ONA_CONTEXT>"""

    prompt = f"""{capsule}

Problem Statement:
{task['title']}
{task['description']}

Generate the surgical patch to fix this bug. Return ONLY valid JSON:"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json"
        }
    }

    t0 = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            latency = round(time.time() - t0, 2)
            usage = data.get("usageMetadata", {})
            patch_data = json.loads(text)
    except Exception as e:
        print(f"[{idx}/5] {tid} -> API/JSON ERROR: {e}")
        results.append({"id": tid, "status": "ERROR", "error": str(e)})
        continue

    # 3. Apply patch
    old_str = patch_data.get("old_string", "")
    new_str = patch_data.get("new_string", "")
    current_content = src_file.read_text()

    if old_str not in current_content:
        print(f"[{idx}/5] {tid} -> PATCH MATCH FAIL: old_string not in target file")
        results.append({"id": tid, "status": "FAIL_PATCH_MISMATCH", "latency_s": latency})
        continue

    src_file.write_text(current_content.replace(old_str, new_str, 1))

    # 4. Run post-patch pytest
    post_res = subprocess.run(["pytest", str(test_file)], capture_output=True, text=True)
    if post_res.returncode == 0:
        print(f"[{idx}/5] {tid} -> ✅ VERIFIED PASS ({latency}s | {usage.get('totalTokenCount', 0)} tok)")
        results.append({
            "id": tid,
            "status": "VERIFIED_PASS",
            "exit_code": 0,
            "latency_s": latency,
            "tokens": usage.get("totalTokenCount", 0)
        })
    else:
        print(f"[{idx}/5] {tid} -> ❌ POST-PATCH PYTEST FAILED (exit code: {post_res.returncode})")
        results.append({
            "id": tid,
            "status": "FAIL_TEST_REJECTED",
            "exit_code": post_res.returncode,
            "latency_s": latency,
            "output": post_res.stdout[-200:]
        })

passed = sum(1 for r in results if r["status"] == "VERIFIED_PASS")
print("\n==================================================================")
print(f" HONEST BENCHMARK RESULTS: {passed} / {len(TASKS)} PASSED ({passed/len(TASKS)*100:.1f}%)")
print(" Verification: Physical pytest execution (zero regexes, zero placeholders)")
print("==================================================================")

out_file = Path("/tmp/honest_swe_5_results.json")
out_file.write_text(json.dumps(results, indent=2))
print(f"Results saved to: {out_file}")
