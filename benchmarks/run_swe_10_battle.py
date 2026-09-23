#!/usr/bin/env python3
"""
Comparative SWE Agent Benchmark (10 Real Tasks):
  Mode A: BEZ JIT (Raw baseline without capsule)
  Mode B: Z JIT (BEZ JEV) (JIT Context OS with deterministic token ranking)
  Mode C: Z JIT + JEV (JIT Context OS with JEV probabilistic decision scoring via OpenRouter)

Verification:
  - 10 real SWE-bench style Python tasks with decoy files.
  - Hard baseline check: Pytest MUST fail before any agent action.
  - Multi-turn agent loop with real tool calls: search_files, read_file, patch, run_tests, done.
  - Post-run verification: Pytest exit code == 0.
  - Zero projections, 100% empirical runtime measurements.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Setup Paths & Keys
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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

from cognitive.jev_engine import JevDecisionScorer, get_jev_scorer, token_overlap_score

BENCH_TMP = Path("/tmp/swe_10_comparison")

# -------------------------------------------------------------------------
# 10 Real Python SWE Tasks
# -------------------------------------------------------------------------
TASKS = [
    {
        "id": "django__django-11099",
        "title": "UsernameValidator allows trailing newline in usernames",
        "description": "ASCIIUsernameValidator and UnicodeUsernameValidator use regex r'^[\\w.@+-]+$'. In Python regex, $ matches before a trailing newline. Use \\Z instead of $ so usernames ending with \\n are rejected.",
        "target_file": "django/contrib/auth/validators.py",
        "test_file": "tests/test_validators.py",
        "files": {
            "django/contrib/auth/validators.py": """import re

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
            "django/contrib/auth/models.py": """# Decoy auth models
class User:
    username = ""
    email = ""
""",
            "django/contrib/auth/forms.py": """# Decoy auth forms
class AuthenticationForm:
    username = ""
""",
            "django/core/validators.py": """# Decoy core validators
def validate_email(value):
    pass
""",
            "tests/test_validators.py": """import pytest
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
"""
        }
    },
    {
        "id": "django__django-11848",
        "title": "parse_http_date two digit year check RFC 7231",
        "description": "RFC 7231 specifies that 2-digit years more than 50 years in the future must be interpreted as past century. Instead of hardcoded year < 70, compare to current_year: if year - (current_year % 100) > 50 -> year += current_century - 100, else year += current_century.",
        "target_file": "django/utils/http.py",
        "test_file": "tests/test_http.py",
        "files": {
            "django/utils/http.py": """import re, datetime

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
            "django/utils/dateparse.py": """# Decoy date parser
def parse_date(value):
    return value
""",
            "django/utils/timezone.py": """# Decoy timezone utils
def now():
    import datetime
    return datetime.datetime.now()
""",
            "tests/test_http.py": """import pytest
from django.utils.http import parse_http_date

def test_rfc7231_year():
    # Year 71 in 2026 is 45 years in future (<= 50) -> MUST be 2071, NOT 1971
    assert parse_http_date("71") == 2071
"""
        }
    },
    {
        "id": "django__django-14382",
        "title": "django-admin startapp with trailing slash results in empty app directory",
        "description": "Calling os.path.basename() on a target with trailing slash (e.g. 'myapp/') returns empty string '', causing CommandError. Strip trailing slashes with target.rstrip('/\\\\') before os.path.basename().",
        "target_file": "django/core/management/templates.py",
        "test_file": "tests/test_templates.py",
        "files": {
            "django/core/management/templates.py": """import os

class CommandError(Exception):
    pass

def validate_name(name):
    if not name:
        raise CommandError("Target directory name cannot be empty")
    return name

def handle_app_creation(app_name, target):
    if target is None:
        top_dir = os.path.abspath(app_name)
    else:
        # Bug: if target has trailing slash e.g. 'foo/', basename is ''
        name = os.path.basename(target)
        validate_name(name)
        top_dir = os.path.abspath(target)
    return top_dir
""",
            "django/core/management/base.py": """# Decoy base command
class BaseCommand:
    def run_from_argv(self, argv): pass
""",
            "django/core/management/commands/startapp.py": """# Decoy startapp command
class Command:
    help = "Starts a Django app"
""",
            "tests/test_templates.py": """import pytest
from django.core.management.templates import handle_app_creation

def test_handle_app_creation_trailing_slash():
    top_dir = handle_app_creation("myapp", "some_path/myapp/")
    assert top_dir.endswith("myapp")
"""
        }
    },
    {
        "id": "django__django-15400",
        "title": "SimpleLazyObject doesn't implement __radd__",
        "description": "SimpleLazyObject is missing __radd__. When an operand is on the left side (e.g. 10 + lazy), Python calls lazy.__radd__(10). Implement __radd__(self, other) to return other + self._setupfunc() (or other + self._wrapped).",
        "target_file": "django/utils/functional.py",
        "test_file": "tests/test_functional.py",
        "files": {
            "django/utils/functional.py": """class SimpleLazyObject:
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
            "django/utils/datastructures.py": """# Decoy datastructures
class MultiValueDict(dict):
    pass
""",
            "django/utils/decorators.py": """# Decoy decorators
def method_decorator(dec):
    return dec
""",
            "tests/test_functional.py": """import pytest
from django.utils.functional import SimpleLazyObject

def test_radd():
    lazy = SimpleLazyObject(lambda: 5)
    assert 10 + lazy == 15
"""
        }
    },
    {
        "id": "astropy__astropy-14995",
        "title": "NDDataRef mask propagation fails when operand has no mask",
        "description": "When operand does not have a mask (operand.mask is None), _arithmetic_mask should return copy of self.mask instead of calling handle_mask with None. Change 'elif operand is None:' to 'elif operand is None or getattr(operand, \"mask\", None) is None:'.",
        "target_file": "astropy/nddata/ndarithmetic.py",
        "test_file": "tests/test_ndarithmetic.py",
        "files": {
            "astropy/nddata/ndarithmetic.py": """import copy

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
            "astropy/nddata/nddata.py": """# Decoy nddata
class NDData: pass
""",
            "astropy/nddata/nddata_base.py": """# Decoy nddata_base
class NDBase: pass
""",
            "tests/test_ndarithmetic.py": """import pytest
from astropy.nddata.ndarithmetic import NDArithmetic, MockOperand

def test_mask_when_operand_mask_is_none():
    obj = NDArithmetic(mask=[1, 0, 1])
    operand = MockOperand(mask=None)
    res = obj._arithmetic_mask(operand, handle_mask=lambda a, b: [x | y for x, y in zip(a, b)])
    assert res == [1, 0, 1]
"""
        }
    },
    {
        "id": "pallets__flask-4045",
        "title": "Blueprint name cannot contain a dot",
        "description": "Creating a Blueprint with a dot '.' in its name breaks nested endpoint routing. In Blueprint.__init__, raise ValueError(\"'name' may not contain a dot '.'\") if '.' in name.",
        "target_file": "flask/blueprints.py",
        "test_file": "tests/test_blueprints.py",
        "files": {
            "flask/blueprints.py": """class Blueprint:
    def __init__(self, name, import_name):
        self.name = name
        self.import_name = import_name
        self.routes = []

    def route(self, rule):
        def decorator(f):
            self.routes.append((rule, f))
            return f
        return decorator
""",
            "flask/app.py": """# Decoy Flask app
class Flask:
    def register_blueprint(self, bp): pass
""",
            "flask/scaffold.py": """# Decoy scaffold
class Scaffold: pass
""",
            "tests/test_blueprints.py": """import pytest
from flask.blueprints import Blueprint

def test_dot_in_blueprint_name():
    with pytest.raises(ValueError, match="may not contain a dot"):
        Blueprint("admin.api", __name__)
"""
        }
    },
    {
        "id": "requests__requests-2148",
        "title": "socket.error in Response.iter_content should be wrapped in ChunkedEncodingError",
        "description": "When socket.error occurs during stream reading in Response.iter_content, requests should catch socket.error and raise ChunkedEncodingError(e) so callers receive a RequestException subclass.",
        "target_file": "requests/models.py",
        "test_file": "tests/test_models.py",
        "files": {
            "requests/__init__.py": "# requests package\n",
            "requests/models.py": """import socket

class RequestException(IOError): pass
class ChunkedEncodingError(RequestException): pass

class Response:
    def iter_content(self, chunk_size=1):
        try:
            yield b"data_chunk_1"
            raise socket.error("socket reset by peer")
        except socket.error as e:
            # Bug: raw socket.error is re-raised directly
            raise e
""",
            "requests/sessions.py": """# Decoy sessions
class Session: pass
""",
            "requests/adapters.py": """# Decoy adapters
class HTTPAdapter: pass
""",
            "tests/test_models.py": """import pytest
from requests.models import Response, ChunkedEncodingError

def test_socket_error_wrapped():
    r = Response()
    with pytest.raises(ChunkedEncodingError):
        list(r.iter_content())
"""
        }
    },
    {
        "id": "django__django-11583",
        "title": "Auto-reloader crashes on empty path in sys.path",
        "description": "iter_modules_and_files() iterates over sys_paths. If sys_paths contains an empty string '' (which happens when current dir is in sys.path), resolving it or passing empty path causes issues. Filter out empty paths: if not p: continue before resolving.",
        "target_file": "django/utils/autoreload.py",
        "test_file": "tests/test_autoreload.py",
        "files": {
            "django/utils/autoreload.py": """from pathlib import Path

def iter_modules_and_files(sys_paths):
    results = []
    for p in sys_paths:
        # Bug: empty string resolves to current directory or causes null byte errors; should be skipped
        resolved = Path(p).resolve()
        results.append(str(resolved))
    return results
""",
            "django/utils/module_loading.py": """# Decoy module loading
def import_string(dotted_path): return None
""",
            "django/core/checks.py": """# Decoy core checks
def run_checks(): return []
""",
            "tests/test_autoreload.py": """import pytest
from pathlib import Path
from django.utils.autoreload import iter_modules_and_files

def test_empty_sys_path():
    paths = ["", "/tmp"]
    res = iter_modules_and_files(paths)
    assert len(res) == 1
    assert res[0] == str(Path("/tmp").resolve())
"""
        }
    },
    {
        "id": "pytest-dev__pytest-5221",
        "title": "getfixturedefs should respect requested scope",
        "description": "When multiple fixtures of different scopes are registered for the same name, getfixturedefs(argname, scope=None) should return the fixture matching the specified scope if scope is provided, instead of always returning the last registered fixture.",
        "target_file": "_pytest/fixtures.py",
        "test_file": "tests/test_fixtures.py",
        "files": {
            "_pytest/__init__.py": "# _pytest package\n",
            "_pytest/fixtures.py": """class FixtureDef:
    def __init__(self, argname, scope="function"):
        self.argname = argname
        self.scope = scope

class FixtureManager:
    def __init__(self):
        self._arg2fixturedefs = {}

    def add_fixture(self, name, fixdef):
        if name not in self._arg2fixturedefs:
            self._arg2fixturedefs[name] = []
        self._arg2fixturedefs[name].append(fixdef)

    def getfixturedefs(self, argname, scope=None):
        defs = self._arg2fixturedefs.get(argname, [])
        if not defs:
            raise KeyError(f"Unknown fixture {argname}")
        # Bug: ignores scope parameter and always returns last fixture
        return defs[-1]
""",
            "_pytest/runner.py": """# Decoy pytest runner
def run_test(): pass
""",
            "_pytest/config.py": """# Decoy pytest config
class Config: pass
""",
            "tests/test_fixtures.py": """import pytest, importlib.util
from pathlib import Path

# Load local fixtures module directly to isolate from runner pytest process
_p = Path(__file__).parent.parent / "_pytest" / "fixtures.py"
_spec = importlib.util.spec_from_file_location("local_fixtures", str(_p))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
FixtureManager = _mod.FixtureManager
FixtureDef = _mod.FixtureDef

def test_getfixturedefs_scope():
    fm = FixtureManager()
    fm.add_fixture("db", FixtureDef("db", scope="session"))
    fm.add_fixture("db", FixtureDef("db", scope="function"))
    res = fm.getfixturedefs("db", scope="session")
    assert res.scope == "session"
"""
        }
    },
    {
        "id": "sympy__sympy-18057",
        "title": "Equality comparison of Expr with None should return False",
        "description": "Comparing an Expr instance with None using Equality(a, b) raises AttributeError because None has no attributes. If either argument is None (or if b is None), Equality should evaluate to False without raising an exception.",
        "target_file": "sympy/core/relational.py",
        "test_file": "tests/test_relational.py",
        "files": {
            "sympy/core/relational.py": """class Expr:
    def __init__(self, name):
        self.name = name

def Equality(a, b):
    # Bug: does not check for None, tries to compare attributes
    if a.name == b.name:
        return True
    return False
""",
            "sympy/core/expr.py": """# Decoy expr
class BasicExpr: pass
""",
            "sympy/core/basic.py": """# Decoy basic
class Basic: pass
""",
            "tests/test_relational.py": """import pytest
from sympy.core.relational import Expr, Equality

def test_equality_with_none():
    x = Expr("x")
    assert Equality(x, None) is False
"""
        }
    }
]

# -------------------------------------------------------------------------
# Repo Setup & Baseline Verification
# -------------------------------------------------------------------------
def setup_task_repo(base_dir: Path, task: Dict[str, Any]) -> None:
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)

    for rel_path, content in task["files"].items():
        file_path = base_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    # Ensure all package directories have __init__.py so Python prioritizes local code over system site-packages
    for p in list(base_dir.rglob("*.py")):
        cur = p.parent
        while cur != base_dir and cur.is_relative_to(base_dir):
            init_file = cur / "__init__.py"
            if not init_file.exists():
                init_file.write_text("# package\n")
            cur = cur.parent


def verify_baseline_failure(base_dir: Path, test_file: str) -> bool:
    env = os.environ.copy()
    if not (base_dir / "_pytest").exists():
        env["PYTHONPATH"] = str(base_dir)
    cmd = ["python3", "-m", "pytest", str(base_dir / test_file)]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return res.returncode != 0


# -------------------------------------------------------------------------
# JIT Context Capsule Builder
# -------------------------------------------------------------------------
def build_jit_capsule(
    repo_dir: Path,
    task: Dict[str, Any],
    use_jev: bool = False
) -> str:
    """Builds Lean JIT Context Capsule (<ONA_CONTEXT>) with or without JEV reranking."""
    query = f"{task['title']} {task['description']}"
    
    # List candidate files in repo
    candidates = []
    for rel_path in task["files"].keys():
        if rel_path.startswith("tests/"):
            continue
        p = repo_dir / rel_path
        content_preview = p.read_text()[:300].replace("\n", " ")
        candidates.append({"key": rel_path, "value": f"{rel_path}: {content_preview}"})

    jev_scores = {}
    if use_jev:
        scorer = get_jev_scorer()
        if scorer.is_available():
            try:
                # Live OpenRouter /api/alpha/decisions scoring
                jev_scores = scorer.score_remote(query, candidates)
            except Exception:
                jev_scores = {}
        reranked = scorer.rerank_hybrid(query, candidates)
    else:
        # Standard token overlap (Deterministic ranking)
        q_tokens = set(w.lower() for w in query.split() if len(w) > 2)
        def _tok_sort(item):
            t_score = token_overlap_score(item["value"], q_tokens)
            return -t_score
        reranked = sorted(candidates, key=_tok_sort)

    top_file = reranked[0]["key"] if reranked else task["target_file"]
    target_path = repo_dir / top_file
    target_code = target_path.read_text() if target_path.exists() else ""
    numbered_lines = "\n".join(f"{i+1:3d}| {line}" for i, line in enumerate(target_code.splitlines()))

    pointers = []
    for r in reranked:
        k = r["key"]
        p_str = f"@file:{k}"
        if use_jev and k in jev_scores:
            p_str += f" (p={jev_scores[k]:.2f})"
        pointers.append(p_str)

    capsule = f"""<ONA_CONTEXT scope="{task['id'].split('__')[0]}" epoch="1" confidence="1.00" complexity="swe_fix">
  [DEV RUNTIME & AST WORKING SET]
    • Target Candidate: {top_file}
    • Candidate Ranking: {", ".join(pointers[:3])}
    • Working Set (Lines & Code):
{numbered_lines}
  [ACTIVE INVARIANTS]
    • ZERO FAKE: Your code patch is verified directly via real pytest execution.
    • RETURN FORMAT: Return ONLY valid JSON matching:
      {{"tool": "patch", "path": "{top_file}", "old_string": "exact unique text", "new_string": "replacement text"}}
      OR use tool calls: search_files, read_file, patch, run_tests, done.
</ONA_CONTEXT>"""
    return capsule


# -------------------------------------------------------------------------
# Agentic SWE Execution Loop
# -------------------------------------------------------------------------
def run_agentic_task(
    task: Dict[str, Any],
    mode: str,
    max_turns: int = 6
) -> Dict[str, Any]:
    task_dir = BENCH_TMP / mode / task["id"]
    setup_task_repo(task_dir, task)

    # 1. Verify baseline test fails
    if not verify_baseline_failure(task_dir, task["test_file"]):
        return {
            "task_id": task["id"],
            "mode": mode,
            "status": "INVALID_BASELINE",
            "passed": False,
            "turns": 0,
            "wall_time_s": 0.0,
            "tokens": 0,
            "discovery_ops": 0,
            "error": "Baseline test passed before fix"
        }

    # 2. Prepare Context & Prompt
    sys_instructions = """You are an autonomous SWE agent solving a software bug in this repository.
You have the following tools available:
1. {"tool": "search_files", "pattern": "string"} -> searches files in repository
2. {"tool": "read_file", "path": "relative/path.py", "offset": 1, "limit": 50} -> reads file with line numbers
3. {"tool": "patch", "path": "relative/path.py", "old_string": "exact code", "new_string": "replacement"} -> surgical patch
4. {"tool": "run_tests"} -> executes pytest on the repository test suite
5. {"tool": "done", "summary": "explanation"} -> finishes the task

Respond ONLY with a single JSON object corresponding to your tool call.
"""

    initial_user_msg = ""
    if mode == "bez_jit":
        initial_user_msg = f"""Problem Statement:
{task['title']}
{task['description']}

Solve this bug in the repository. Start by investigating or modifying the relevant files."""

    elif mode == "jit_bez_jev":
        capsule = build_jit_capsule(task_dir, task, use_jev=False)
        initial_user_msg = f"""{capsule}

Problem Statement:
{task['title']}
{task['description']}

Solve this bug using the surgical patch tool. The target file and working set are provided in the capsule above."""

    elif mode == "jit_z_jev":
        capsule = build_jit_capsule(task_dir, task, use_jev=True)
        initial_user_msg = f"""{capsule}

Problem Statement:
{task['title']}
{task['description']}

Solve this bug using the surgical patch tool. The target file and working set are provided in the capsule above."""

    messages = [
        {"role": "user", "parts": [{"text": f"{sys_instructions}\n\n{initial_user_msg}"}]}
    ]

    total_tokens = 0
    discovery_ops = 0
    task_passed = False
    last_error = None
    t0 = time.time()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GOOGLE_API_KEY}"

    turn = 0
    for turn in range(1, max_turns + 1):
        payload = {
            "contents": messages,
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )

        tool_call = None
        text = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=35) as resp:
                    data = json.loads(resp.read().decode())
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    usage = data.get("usageMetadata", {})
                    total_tokens += usage.get("totalTokenCount", 0)
                    tool_call = json.loads(text)
                    break
            except Exception as e:
                last_error = f"API/Parse Error: {e}"
                time.sleep(1.0 * (attempt + 1))
        if not tool_call:
            break

        tool_name = tool_call.get("tool")

        # Execute Tool
        tool_output = ""
        if tool_name == "search_files":
            discovery_ops += 1
            pat = tool_call.get("pattern", "").lower()
            matches = []
            for root, _, files in os.walk(task_dir):
                for f in files:
                    if f.endswith(".py"):
                        p = Path(root) / f
                        try:
                            for idx, line in enumerate(p.read_text().splitlines(), 1):
                                if pat in line.lower():
                                    matches.append(f"{p.relative_to(task_dir)}:{idx}: {line.strip()}")
                        except Exception:
                            pass
            tool_output = "\n".join(matches[:15]) if matches else "No matches found."

        elif tool_name == "read_file":
            discovery_ops += 1
            rel_path = tool_call.get("path", "")
            target_p = task_dir / rel_path
            if not rel_path or not target_p.exists() or target_p.is_dir():
                tool_output = f"Error: Path '{rel_path}' is invalid, is a directory, or does not exist."
            else:
                lines = target_p.read_text().splitlines()
                off = max(1, tool_call.get("offset", 1))
                lim = tool_call.get("limit", 40)
                slice_lines = lines[off - 1 : off - 1 + lim]
                tool_output = "\n".join(f"{off + idx:3d}| {l}" for idx, l in enumerate(slice_lines))

        elif tool_name == "patch":
            rel_path = tool_call.get("path", "")
            target_p = task_dir / rel_path
            if not rel_path or not target_p.exists() or target_p.is_dir():
                tool_output = f"Error: Path '{rel_path}' is invalid, is a directory, or does not exist."
            else:
                old_s = tool_call.get("old_string", "")
                new_s = tool_call.get("new_string", "")
                content = target_p.read_text()
                if old_s not in content:
                    tool_output = "Error: old_string not found in file. Patch failed."
                else:
                    new_content = content.replace(old_s, new_s, 1)
                    target_p.write_text(new_content)
                    tool_output = f"Success: Patch applied cleanly to '{rel_path}'."

        elif tool_name == "run_tests":
            env = os.environ.copy()
            if not (task_dir / "_pytest").exists():
                env["PYTHONPATH"] = str(task_dir)
            cmd = ["python3", "-m", "pytest", str(task_dir / task["test_file"])]
            res = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if res.returncode == 0:
                tool_output = "Pytest: ALL TESTS PASSED (exit code 0)."
                task_passed = True
            else:
                out_summary = res.stdout[-400:] if res.stdout else res.stderr[-400:]
                tool_output = f"Pytest: TESTS FAILED (exit code {res.returncode}):\n{out_summary}"
                task_passed = False

        elif tool_name == "done":
            break

        else:
            tool_output = f"Unknown tool: {tool_name}"

        # Feed tool result back to agent
        messages.append({"role": "model", "parts": [{"text": text}]})
        messages.append({"role": "user", "parts": [{"text": f"Tool Result:\n{tool_output}\n\nNext tool call:"}]})

        # Early exit if tests passed and agent patched
        if tool_name == "run_tests" and task_passed:
            break

    # Final Verification: Re-run pytest on final repo state
    env = os.environ.copy()
    if not (task_dir / "_pytest").exists():
        env["PYTHONPATH"] = str(task_dir)
    final_res = subprocess.run(["python3", "-m", "pytest", str(task_dir / task["test_file"])], env=env, capture_output=True, text=True)
    verified_pass = (final_res.returncode == 0)
    wall_time = round(time.time() - t0, 2)

    return {
        "task_id": task["id"],
        "mode": mode,
        "status": "PASS" if verified_pass else "FAIL",
        "passed": verified_pass,
        "turns": turn,
        "wall_time_s": wall_time,
        "tokens": total_tokens,
        "discovery_ops": discovery_ops,
        "error": last_error
    }


# -------------------------------------------------------------------------
# Main Execution Runner
# -------------------------------------------------------------------------
def main():
    modes = ["bez_jit", "jit_bez_jev", "jit_z_jev"]
    mode_labels = {
        "bez_jit": "1. BEZ JIT (Raw Baseline)",
        "jit_bez_jev": "2. Z JIT (BEZ JEV - Heuristic Token)",
        "jit_z_jev": "3. Z JIT + JEV (Probabilistic Decision Engine)"
    }

    if BENCH_TMP.exists():
        shutil.rmtree(BENCH_TMP)
    BENCH_TMP.mkdir(parents=True)

    print("=" * 70)
    print(" ⚔️  SWE AGENT COMPARATIVE BENCHMARK: 10 TASKS × 3 MODES")
    print("=======================================================")
    print("• Model:               Gemini 3.8 Flash (temperature: 0.0)")
    print("• JEV Engine:          ~typesafe/jev-latest via OpenRouter (/api/alpha/decisions)")
    print("• Verification:        Physical pytest execution on disk (exit code == 0)")
    print("• Tasks:               10 Real SWE Python bugs with decoy files")
    print("=" * 70)

    all_results = {m: [] for m in modes}

    for t_idx, task in enumerate(TASKS, 1):
        print(f"\n[{t_idx:2d}/10] 🎯 TASK: {task['id']} — {task['title'][:50]}...")
        
        for m in modes:
            print(f"   ├─ Running {mode_labels[m]}...", end="", flush=True)
            res = run_agentic_task(task, mode=m, max_turns=8)
            all_results[m].append(res)
            
            icon = "✅ PASS" if res["passed"] else "❌ FAIL"
            print(f" -> {icon} | {res['wall_time_s']}s | turns: {res['turns']} | tok: {res['tokens']} | disc: {res['discovery_ops']}")
        
        # Save intermediate snapshot
        out_file = Path("/tmp/swe_agent_10_comparison_results.json")
        out_file.write_text(json.dumps({"details": all_results}, indent=2))

    # -------------------------------------------------------------------------
    # Aggregated Summary Table
    # -------------------------------------------------------------------------
    print("\n" + "=" * 75)
    print(" 📊 FINAL SWE AGENT COMPARATIVE RESULTS TABLE")
    print("=" * 75)
    header = f"{'Configuration':<38} | {'Pass Rate':<10} | {'Total Time':<10} | {'Avg Turns':<10} | {'Tokens':<8} | {'Disc Ops'}"
    print(header)
    print("-" * 75)

    summary_stats = {}
    for m in modes:
        res_list = all_results[m]
        passed_count = sum(1 for r in res_list if r["passed"])
        pass_rate = f"{passed_count}/10 ({passed_count/10*100:.0f}%)"
        total_time = round(sum(r["wall_time_s"] for r in res_list), 1)
        avg_turns = round(sum(r["turns"] for r in res_list) / len(res_list), 1)
        total_tokens = sum(r["tokens"] for r in res_list)
        total_disc = sum(r["discovery_ops"] for r in res_list)

        summary_stats[m] = {
            "passed": passed_count,
            "pass_rate": pass_rate,
            "total_time_s": total_time,
            "avg_turns": avg_turns,
            "total_tokens": total_tokens,
            "discovery_ops": total_disc
        }
        print(f"{mode_labels[m]:<38} | {pass_rate:<10} | {total_time:>8}s | {avg_turns:>9} | {total_tokens:>8} | {total_disc:>8}")

    print("=" * 75)

    # Save output artifacts
    out_file = Path("/tmp/swe_agent_10_comparison_results.json")
    out_file.write_text(json.dumps({"summary": summary_stats, "details": all_results}, indent=2))
    print(f"\n[Artifact saved to: {out_file}]")


if __name__ == "__main__":
    main()
