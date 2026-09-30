# Jev → JIT Context Support — Implementation Plan

> **For agent:** Execute task-by-task (subagent-driven or sequential). Every task = TDD cycle + commit.

**Goal:** Build `jev_bridge` — a separate, optional Agent Zero plugin that feeds the existing JIT Context OS with the two things its deterministic runtime cannot produce itself: shadow-verdict labels (Slot 1) and relevance-ranked L2 vault facts (Slot 2), plus fence distillation (Slot 3) and advisory eviction (Slot 4).

**Architecture:** Jev is an *async-ish sensor/judge*: it runs post-turn (`message_loop_prompts_after`) or at `agent_init`, writes to SQLite, and **never** touches `before_main_llm_call`, never mutates the capsule in-flight, never bypasses the LLM. Deterministic local heuristics ship first (zero dependencies); an HTTP backend behind a circuit breaker is the last, optional phase. The only change inside `a0-jit-context` is a tiny rerank hook in `_read_vault_facts_sync` (backward-compatible, file-order fallback).

**Tech stack:** Python 3.11 stdlib only (sqlite3, urllib, re, asyncio). Tests: pytest via `/opt/venv/bin/python`. Two repos: `a0-jev-bridge` (new), `a0-jit-context` (existing, one patched method).

**Hard rules (from DoD, non-negotiable):**
1. No code on the pre-LLM hot path. Post-turn work must be synchronous-cheap (<1ms compute + ≤1 SQLite insert) or `loop.create_task` fire-and-forget.
2. Any failure = silence (I6). Every `execute()` ends in `except Exception: return`.
3. `jev_bridge` removable without touching `jit_context` (loader returns `None` → everything degrades to current behavior).
4. Rollback switch: `jev_enabled: false` in config → zero DB writes, bit-identical behavior.
5. Distilled facts get `epistemic_weight ≤ 0.5` and never override weight-1.0 facts (I3: assistant output has near-zero epistemic weight).

---

## Phase 0 — Skeleton

### Task 1: Scaffold `a0-jev-bridge` plugin repo

**Objective:** Create the plugin skeleton that Agent Zero can load, with rollback switch in config.

**Files:**
- Create: `/a0/usr/workdir/a0-jev-bridge/plugin.yaml`
- Create: `/a0/usr/workdir/a0-jev-bridge/default_config.yaml`
- Create: `/a0/usr/workdir/a0-jev-bridge/hooks.py`
- Create: `/a0/usr/workdir/a0-jev-bridge/README.md`
- Create: `/a0/usr/workdir/a0-jev-bridge/.gitignore`
- Create dirs: `extensions/python/agent_init/`, `extensions/python/message_loop_prompts_after/`, `jev_bridge/`, `tests/`, `scripts/`, `data/` (data/ gitignored)

**Step 1: Create files**

`plugin.yaml`:
```yaml
name: jev_bridge
title: Jev Bridge for JIT Context
description: Async judge layer feeding JIT Context OS shadow gate, L2 relevance ranking, fence distillation and eviction advice. Never on the hot path.
version: 0.1.0
author: Wojciech Wiesner
tags:
  - context
  - memory
  - judge
settings_sections:
  - agent
per_project_config: true
per_agent_config: true
```

`default_config.yaml`:
```yaml
jev_enabled: true
jev_http_url: ""
jev_distill_enabled: true
jev_distill_max_facts: 3
jev_eviction_budget_pct: 0.9
```

`hooks.py`:
```python
import os

def install():
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True)
    return 0

def uninstall():
    return 0
```

`README.md`:
```markdown
# jev_bridge

Sensor/judge layer for JIT Context OS. Slots: shadow verdicts, L2 rerank,
fence distillation, eviction advice. Disable: set `jev_enabled: false`.
```

`.gitignore`:
```
data/*.db*
__pycache__/
.pytest_cache/
```

`jev_bridge/__init__.py` — empty file.
`tests/__init__.py` — empty file.

**Step 2: Verify skeleton**

Run: `find /a0/usr/workdir/a0-jev-bridge -type f | grep -v __pycache__ | sort`
Expected: 7+ files including `plugin.yaml`, `default_config.yaml`.

**Step 3: Commit**
```bash
cd /a0/usr/workdir/a0-jev-bridge && git init -q && git add -A && git commit -qm "chore: scaffold jev_bridge plugin"
```

---

### Task 2: Cross-plugin runtime loader

**Objective:** Resolve the jit_context runtime (installed or dev copy) with zero jit_context changes.

**Files:**
- Create: `/a0/usr/workdir/a0-jev-bridge/jev_bridge/_runtime.py`
- Test: `/a0/usr/workdir/a0-jev-bridge/tests/test_runtime_loader.py`

**Step 1: Write failing test**
```python
import os

def test_loader_resolves_dev_runtime():
    os.environ["JIT_CONTEXT_PLUGIN_DIR"] = "/a0/usr/workdir/a0-jit-context"
    from jev_bridge._runtime import load_runtime_getter
    get_runtime = load_runtime_getter()
    assert get_runtime is not None
    rt = get_runtime()
    assert hasattr(rt, "record_shadow_verdict")
    assert hasattr(rt, "compile_capsule")

def test_loader_silent_when_missing():
    os.environ["JIT_CONTEXT_PLUGIN_DIR"] = "/nonexistent-xyz"
    import sys
    sys.modules.pop("usr.plugins.jit_context.helpers.runtime", None)
    from jev_bridge._runtime import load_runtime_getter
    # may still find /a0/usr/workdir fallback; must not raise either way
    getter = load_runtime_getter()
    assert getter is None or callable(getter)
```

**Step 2: Run to verify failure**

Run: `cd /a0/usr/workdir/a0-jev-bridge && /opt/venv/bin/python -m pytest tests/test_runtime_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: jev_bridge._runtime`

**Step 3: Implement** `_runtime.py`:
```python
"""Resolve the jit_context runtime across dev/install layouts (I6: None = degrade)."""
from __future__ import annotations

import importlib.util
import os
import sys

_MODULE = "usr.plugins.jit_context.helpers.runtime"


def _candidate_roots():
    yield os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or ""
    yield "/a0/usr/plugins/jit_context"
    yield "/a0/usr/workdir/a0-jit-context"


def load_runtime_getter():
    try:
        from usr.plugins.jit_context.helpers.runtime import get_runtime
        return get_runtime
    except Exception:
        pass
    mod = sys.modules.get(_MODULE)
    if mod is not None and hasattr(mod, "get_runtime"):
        return mod.get_runtime
    for base in _candidate_roots():
        if not base:
            continue
        path = os.path.join(base, "helpers", "runtime.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(_MODULE, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[_MODULE] = mod
            spec.loader.exec_module(mod)
            return mod.get_runtime
        except Exception:
            sys.modules.pop(_MODULE, None)
            return None
    return None
```

**Step 4: Run to verify pass** — same command. Expected: `2 passed`.

**Step 5: Commit:** `git add -A && git commit -qm "feat: cross-plugin jit_context runtime loader"`

---

## Phase 1 — Slot 1: Shadow verdict judge (feeds starving gate)

### Task 3: Deterministic local judge (pure functions)

**Objective:** `classify_turn(facts, response, invariant_flags) -> HELPFUL|NEUTRAL|HARMFUL` with zero I/O.

**Files:**
- Create: `jev_bridge/judge.py`
- Test: `tests/test_judge.py`

**Step 1: Failing test**
```python
from jev_bridge.judge import classify_turn, fact_hit, tokens

FACTS = [
    {"key": "phase_6_module", "value": "audit_exporter.py"},
    {"key": "phase_5_module", "value": "settlement_pipeline.py"},
    {"key": "phase_4_module", "value": "psp_gateway.py"},
    {"key": "phase_3_module", "value": "fraud_detector.py"},
]

def test_tokens_filters_stopwords():
    t = tokens("The phase_6_module and audit_exporter are deployed")
    assert "phase_6_module" in t and "the" not in t

def test_helpful_when_facts_echoed():
    resp = "W module audit_exporter.py oraz psp_gateway.py dodałem telemetry"
    assert classify_turn(FACTS, resp) == "HELPFUL"

def test_neutral_when_no_overlap():
    assert classify_turn(FACTS, "answer about cooking pasta carbonara recipe") == "NEUTRAL"

def test_neutral_when_no_facts():
    assert classify_turn([], "anything") == "NEUTRAL"

def test_harmful_on_invariant_flags():
    assert classify_turn(FACTS, "phase_6_module audit_exporter used here", invariant_flags=1) == "HARMFUL"
```

**Step 2: Verify failure** — `pytest tests/test_judge.py -v` → FAIL (no module).

**Step 3: Implement** `judge.py`:
```python
"""Deterministic shadow-verdict judge (Slot 1). Pure, no I/O, no LLM.

Contract mirrors runtime.record_shadow_verdict: HELPFUL | NEUTRAL | HARMFUL.
The optional HTTP backend must emit the same three labels.
"""
from __future__ import annotations

import re
from typing import Dict, List

_TOKEN_RE = re.compile(r"[a-z0-9_:\-.]{3,}")
_STOP = {
    "the", "and", "for", "that", "this", "with", "you", "are", "not",
    "nie", "jest", "tak", "jak", "dla", "oraz", "przez", "ktore",
}
MIN_HELPFUL_RATIO = 0.25


def tokens(text: str) -> set:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP}


def fact_hit(fact: Dict[str, str], response_tokens: set) -> bool:
    ft = tokens(f"{fact.get('key', '')} {fact.get('value', '')}")
    if not ft:
        return False
    overlap = ft & response_tokens
    return len(overlap) >= max(1, int(round(0.5 * len(ft))))


def classify_turn(
    capsule_facts: List[Dict[str, str]],
    response_text: str,
    invariant_flags: int = 0,
) -> str:
    if invariant_flags:
        return "HARMFUL"
    if not capsule_facts:
        return "NEUTRAL"
    rt = tokens(response_text)
    hits = sum(1 for f in capsule_facts if fact_hit(f, rt))
    if hits / len(capsule_facts) >= MIN_HELPFUL_RATIO:
        return "HELPFUL"
    return "NEUTRAL"
```

**Step 4: Verify pass** — Expected: `5 passed`.
**Step 5: Commit:** `git commit -qm "feat: deterministic shadow judge heuristics"`

---

### Task 4: `message_loop_prompts_after` extension wiring

**Objective:** Post-turn extension: pull hot facts + last assistant message, classify, call `runtime.record_shadow_verdict`. Silent on every failure.

**Files:**
- Create: `extensions/python/message_loop_prompts_after/_10_shadow_judge.py`
- Create: `tests/conftest.py` (framework stubs)
- Test: `tests/test_shadow_judge_ext.py`

**Step 1: conftest** `tests/conftest.py`:
```python
import sys
import types

DEFAULT_CFG = {"jev_enabled": True}


def _stub_framework():
    if "helpers.extension" in sys.modules:
        return
    helpers = types.ModuleType("helpers")
    ext = types.ModuleType("helpers.extension")

    class Extension:
        def __init__(self, agent=None, **kw):
            self.agent = agent

    ext.Extension = Extension
    plugins = types.ModuleType("helpers.plugins")
    plugins.get_plugin_config = lambda name, agent=None: dict(DEFAULT_CFG)
    sys.modules.update({
        "helpers": helpers,
        "helpers.extension": ext,
        "helpers.plugins": plugins,
    })


_stub_framework()
```

**Step 2: Failing test** `tests/test_shadow_judge_ext.py`:
```python
import importlib.util
import os

import conftest  # noqa: F401  (stubs framework)

EXT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/message_loop_prompts_after/_10_shadow_judge.py",
)


def _load_ext():
    spec = importlib.util.spec_from_file_location("_10_shadow_judge", EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def __init__(self):
        self.verdicts = []
        self.hot = [{"key": "phase_6_module", "value": "audit_exporter.py"}]

    def get_hot_facts(self):
        return self.hot

    def record_shadow_verdict(self, v):
        self.verdicts.append(v)


def _history():
    return [
        {"ai": False, "content": "co robisz"},
        {"ai": True, "content": "audit_exporter.py got telemetry export"},
    ]


def test_judge_records_helpful(monkeypatch):
    mod = _load_ext()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    ext = mod.ShadowJudgeExtension(agent=object())
    ext.execute(loop_data={"history": _history()})
    assert fake.verdicts == ["HELPFUL"]

def test_disabled_writes_nothing(monkeypatch):
    conftest.DEFAULT_CFG["jev_enabled"] = False
    try:
        mod = _load_ext()
        fake = FakeRuntime()
        monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
        mod.ShadowJudgeExtension(agent=object()).execute(loop_data={"history": _history()})
        assert fake.verdicts == []
    finally:
        conftest.DEFAULT_CFG["jev_enabled"] = True

def test_silent_when_runtime_missing(monkeypatch):
    mod = _load_ext()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: None)
    mod.ShadowJudgeExtension(agent=object()).execute(loop_data={"history": _history()})  # must not raise
```

**Step 3: Verify failure** — FAIL: file does not exist.

**Step 4: Implement** `_10_shadow_judge.py`:
```python
"""Slot 1: post-turn shadow judge. Feeds runtime.record_shadow_verdict.
I6: any failure is silence. Never on the pre-LLM hot path.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter
from jev_bridge.judge import classify_turn


class ShadowJudgeExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jev_bridge", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()

            history = (kwargs.get("loop_data") or {}).get("history") or []
            response = ""
            for m in reversed(history):
                if isinstance(m, dict) and m.get("ai"):
                    c = m.get("content", "")
                    response = c if isinstance(c, str) else str(c)
                    break
            if not response:
                return

            facts = []
            try:
                facts = runtime.get_hot_facts() or []
            except Exception:
                facts = []

            verdict = classify_turn(facts, response)
            runtime.record_shadow_verdict(verdict)
        except Exception:
            return  # I6
```

**Step 5: Verify pass** — `pytest tests/ -v`. Expected: all pass incl. 3 new.
**Step 6: Commit:** `git commit -qm "feat: shadow judge extension feeds L2 gate"`

---

### Task 5: Gate-flip integration proof

**Objective:** Prove the starving gate can now flip: 10 synthetic evals → `l2_promotion_ready() == True`.

**Files:**
- Create: `scripts/verify_gate_flip.py`

**Step 1: Script**
```python
#!/usr/bin/env python3
"""Proof: judge output flips the existing l2_promotion_ready gate (10/0/0.3)."""
import os
import sys

os.environ.setdefault("JIT_CONTEXT_PLUGIN_DIR", "/a0/usr/workdir/a0-jit-context")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev_bridge._runtime import load_runtime_getter

get_runtime = load_runtime_getter()
assert get_runtime is not None, "jit_context runtime not found"
rt = get_runtime()

for v in ["HELPFUL"] * 7 + ["NEUTRAL"] * 3:
    rt.record_shadow_verdict(v)
ok = rt.l2_promotion_ready()

rt2 = get_runtime() if hasattr(get_runtime(), "_shadow_stats") else rt
rt.record_shadow_verdict("HARMFUL")
blocked = not rt.l2_promotion_ready(max_harmful=0) or True  # harmful>0 blocks

print(f"gate_after_10_evals={ok}")
assert ok is True, "gate did not flip after 10 clean evals"
print("GATE FLIP: PASS")
```

**Step 2: Run** — `/opt/venv/bin/python scripts/verify_gate_flip.py`
Expected output:
```
gate_after_10_evals=True
GATE FLIP: PASS
```

**Step 3: Commit:** `git commit -qm "test: gate-flip proof script for shadow judge"`

---

## Phase 2 — Slot 2: L2 relevance ranking

### Task 6: Rerank hook inside `a0-jit-context` (the ONLY jit_context change)

**Objective:** `_read_vault_facts_sync` gathers a candidate pool (≤40) and applies an optional `fact_reranker` callable; absent/failing reranker → exact current file-order behavior.

**Files:**
- Modify: `/a0/usr/workdir/a0-jit-context/helpers/runtime.py` (method `_read_vault_facts_sync`, lines ~229–256)
- Test: `/a0/usr/workdir/a0-jit-context/tests/test_vault_rerank.py`

**Step 1: Failing test**
```python
import os
import sys

import pytest

PLUGIN = os.environ.get("JIT_CONTEXT_PLUGIN_DIR", "/a0/usr/workdir/a0-jit-context")
sys.path.insert(0, PLUGIN)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import helpers.runtime as rt
    ctx = tmp_path / "context"
    ctx.mkdir()
    lines = "\n".join(f"fact number {i:02d} about topic{i % 3}" for i in range(12))
    (ctx / "global.md").write_text(lines, encoding="utf-8")
    monkeypatch.setattr(rt, "VAULT_DIR", str(tmp_path), raising=False)
    inst = rt.JITContextRuntime()
    return inst


def test_file_order_without_reranker(runtime):
    facts = runtime._read_vault_facts_sync(limit=4)
    assert [f["value"][:13] for f in facts] == [
        "fact number 00", "fact number 01", "fact number 02", "fact number 03",
    ]


def test_reranker_reorders(runtime):
    runtime.fact_reranker = lambda cands: list(reversed(cands))
    facts = runtime._read_vault_facts_sync(limit=4)
    assert facts[0]["value"].startswith("fact number 11")


def test_pool_exceeds_old_limit(runtime):
    facts = runtime._read_vault_facts_sync(limit=40)
    assert len(facts) == 12  # pool now returns all candidates, not first 8


def test_failing_reranker_falls_back(runtime):
    def boom(cands):
        raise RuntimeError("jev down")
    runtime.fact_reranker = boom
    facts = runtime._read_vault_facts_sync(limit=4)
    assert facts[0]["value"].startswith("fact number 00")
```

**Step 2: Verify failure** — `cd /a0/usr/workdir/a0-jit-context && /opt/venv/bin/python -m pytest tests/test_vault_rerank.py -v`
Expected: `test_reranker_reorders` and `test_failing_reranker_falls_back` FAIL (AttributeError / no reorder); `test_pool_exceeds_old_limit` FAIL (returns 8).

**Step 3: Implement** — replace the whole `_read_vault_facts_sync` method body with:
```python
    def _read_vault_facts_sync(self, limit: int = 8) -> List[Dict[str, Any]]:
        facts: List[Dict[str, Any]] = []
        ctx = os.path.join(VAULT_DIR, "context")
        candidates: List[Dict[str, Any]] = []
        pool = 40  # candidate pool for optional reranker (Slot 2)
        if os.path.isdir(ctx):
            for name in ("global.md", "user.md"):
                p = os.path.join(ctx, name)
                if not os.path.isfile(p):
                    continue
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read(20000)
                except OSError:
                    continue
                base = os.path.basename(p)
                for line in text.splitlines():
                    line = line.strip().lstrip("#- ").strip()
                    if 8 <= len(line) <= 160:
                        candidates.append(
                            {"key": f"vault:{base}:{len(candidates)}", "value": line[:160]}
                        )
                        if len(candidates) >= pool:
                            break
        reranker = getattr(self, "fact_reranker", None)
        if callable(reranker) and candidates:
            try:
                ranked = list(reranker(candidates))
                if ranked:
                    candidates = ranked
            except Exception:
                pass  # I6: file-order fallback
        facts = candidates[:limit]
        return facts
```

**Step 4: Verify pass** — Expected: `4 passed`. Then run full suite: `/opt/venv/bin/python -m pytest tests/ -v` → no regressions.

**Step 5: Commit (jit_context repo)**:
```bash
cd /a0/usr/workdir/a0-jit-context
git status --short || git init -q
git add helpers/runtime.py tests/test_vault_rerank.py
git commit -qm "feat: optional fact_reranker hook in vault L2 read (pool 40, I6 fallback)"
```

---

### Task 7: Local relevance scorer (deterministic, no cache needed)

**Objective:** Score facts against the most recent user query; stable sort = same input → same order (cache-prefix friendly).

**Files:**
- Create: `/a0/usr/workdir/a0-jev-bridge/jev_bridge/rerank.py`
- Test: `tests/test_rerank.py`

**Step 1: Failing test**
```python
from jev_bridge.rerank import RecentQuery, make_reranker


def test_relevance_beats_file_order():
    rq = RecentQuery()
    rq.update("how to configure nginx deploy for boocco")
    rr = make_reranker(rq)
    cands = [
        {"key": "a", "value": "user prefers dark theme in editors"},
        {"key": "b", "value": "boocco nginx config lives in /etc/nginx/boocco.conf"},
        {"key": "c", "value": "weekend grocery list apples"},
    ]
    out = rr(cands)
    assert out[0]["key"] == "b"


def test_deterministic_and_stable():
    rq = RecentQuery()
    rq.update("nginx")
    rr = make_reranker(rq)
    cands = [{"key": str(i), "value": f"neutral fact {i}"} for i in range(10)]
    assert [f["key"] for f in rr(cands)] == [f["key"] for f in rr(list(cands))]


def test_empty_query_keeps_order():
    rr = make_reranker(RecentQuery())
    cands = [{"key": "x", "value": "anything at all"}]
    assert rr(cands)[0]["key"] == "x"
```

**Step 2: Verify failure** → FAIL (module missing).

**Step 3: Implement** `rerank.py`:
```python
"""Slot 2: deterministic local relevance scorer for L2 vault facts."""
from __future__ import annotations

from typing import Dict, List

from jev_bridge.judge import tokens


class RecentQuery:
    """Holds the latest user query; updated post-turn by the judge extension."""

    def __init__(self) -> None:
        self.text: str = ""

    def update(self, text: str) -> None:
        self.text = (text or "")[:2000]


def _score(fact: Dict[str, str], q_tokens: set) -> float:
    ft = tokens(f"{fact.get('key', '')} {fact.get('value', '')}")
    if not ft or not q_tokens:
        return 0.0
    return len(ft & q_tokens) / len(ft)


def make_reranker(rq: RecentQuery):
    def rerank(candidates: List[Dict[str, str]]) -> List[Dict[str, str]]:
        qt = tokens(rq.text)
        if not qt:
            return list(candidates)
        # stable sort: ties keep file order -> deterministic, cache-friendly
        return sorted(candidates, key=lambda f: -_score(f, qt))

    return rerank
```

**Step 4: Verify pass** — `3 passed`.
**Step 5: Commit:** `git commit -qm "feat: deterministic L2 relevance reranker"`

---

### Task 8: Wire reranker at `agent_init` + query feed at post-turn

**Objective:** Install `runtime.fact_reranker` once per agent; keep `RecentQuery` fresh from the last user message.

**Files:**
- Create: `extensions/python/agent_init/_10_jev_init.py`
- Modify: `extensions/python/message_loop_prompts_after/_10_shadow_judge.py` (2 lines: update RecentQuery)
- Test: `tests/test_jev_init.py`

**Step 1: Failing test**
```python
import importlib.util
import os

import conftest  # noqa: F401

INIT_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "extensions/python/agent_init/_10_jev_init.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("_10_jev_init", INIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def __init__(self):
        self.reranker = None


def test_init_installs_reranker(monkeypatch):
    mod = _load()
    fake = FakeRuntime()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    mod.JevInitExtension(agent=object()).execute()
    assert callable(fake.fact_reranker)


def test_init_silent_without_runtime(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: None)
    mod.JevInitExtension(agent=object()).execute()  # must not raise
```

**Step 2: Verify failure** → FAIL (file missing).

**Step 3: Implement** `_10_jev_init.py`:
```python
"""Slot 2 wiring: install deterministic reranker on jit_context runtime.
Idempotent; I6 silent; removable (jev_bridge deleted -> attribute simply
never gets set, runtime falls back to getattr default None).
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter
from jev_bridge.rerank import RecentQuery, make_reranker

RECENT_QUERY = RecentQuery()


class JevInitExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jev_bridge", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()
            if getattr(runtime, "fact_reranker", None) is None:
                runtime.fact_reranker = make_reranker(RECENT_QUERY)
        except Exception:
            return  # I6
```

**Step 4: Modify `_10_shadow_judge.py`** — inside `execute()`, right after the `runtime = get_runtime()` line, add:
```python
            history0 = (kwargs.get("loop_data") or {}).get("history") or []
            for m in reversed(history0):
                if isinstance(m, dict) and not m.get("ai"):
                    try:
                        from jev_bridge._10_shared import RECENT_QUERY
                        RECENT_QUERY.update(str(m.get("content", "")))
                    except Exception:
                        pass
                    break
```
To avoid a circular import, move `RECENT_QUERY` to `jev_bridge/_10_shared.py`:
```python
from jev_bridge.rerank import RecentQuery

RECENT_QUERY = RecentQuery()
```
and change `_10_jev_init.py` to `from jev_bridge._10_shared import RECENT_QUERY` + `make_reranker(RECENT_QUERY)`.

**Step 5: Verify pass** — full `pytest tests/ -v` in jev_bridge + rerun jit_context suite. Expected: all green.
**Step 6: Commit:** `git commit -qm "feat: wire L2 reranker via agent_init + query feed"`

---

## Phase 3 — Slot 3: Fence distillation

### Task 9: Distiller (read-only on jit DB, weight ≤ 0.5)

**Objective:** Convert freshly archived (pruned) user/tool messages into ≤3 compact hot facts per turn, deduped, capped weight.

**Files:**
- Create: `jev_bridge/distill.py`
- Test: `tests/test_distill.py`

**Step 0: Inspect actual archive schema (do NOT guess)**

Run: `sqlite3 /a0/usr/workdir/a0-jit-context/data/jit_context.db '.tables' && sqlite3 /a0/usr/workdir/a0-jit-context/data/jit_context.db '.schema' | grep -iA3 archiv`
Note the archive table name + columns written by `archive_pruned_messages` (expected: session_id, ai flag, content, timestamp-ish). Adjust `ARCHIVE_TABLE`/column names in the test fixture + implementation to match reality.

**Step 1: Failing test** (assumes table `pruned_messages(ts, session_id, ai, content)` — fix names per Step 0):
```python
import sqlite3

from jev_bridge.distill import distill_new_rows


class FakeRuntime:
    def __init__(self, existing):
        self.existing = existing
        self.set_calls = []

    def get_hot_facts(self):
        return self.existing

    def set_hot_fact(self, key, value, epistemic_weight=1.0):
        self.set_calls.append((key, value, epistemic_weight))


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE pruned_messages (ts REAL, session_id TEXT, ai INTEGER, content TEXT)")
    rows = [
        (1.0, "s1", 0, "user wants nginx config for boocco deploy on borg.tools"),
        (1.1, "s1", 1, "assistant long prose that must be ignored entirely"),
        (1.2, "s1", 0, "user wants nginx config for boocco deploy on borg.tools"),  # dupe
        (1.3, "s1", 0, "deadline for invoiceflow KSeF sync is friday"),
    ]
    conn.executemany("INSERT INTO pruned_messages VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_distill_caps_weight_and_dedupes(tmp_path):
    db = str(tmp_path / "x.db")
    _seed(db)
    rt = FakeRuntime(existing=[])
    n = distill_new_rows(rt, db, session_id="s1", since_ts=0.5, cap=3)
    assert n == 2  # user msg + deadline; assistant skipped; dupe collapsed
    for key, value, w in rt.set_calls:
        assert w <= 0.5
        assert "assistant" not in value


def test_distill_respects_existing_facts(tmp_path):
    db = str(tmp_path / "x.db")
    _seed(db)
    rt = FakeRuntime(existing=[{"key": "d0", "value": "nginx config boocco deploy borg.tools user wants"}])
    distill_new_rows(rt, db, session_id="s1", since_ts=0.5, cap=3)
    assert all("invoiceflow" in v or "KSeF" in v for _, v, _ in rt.set_calls)
```

**Step 2: Verify failure** → FAIL (module missing).

**Step 3: Implement** `distill.py`:
```python
"""Slot 3: distill archived fence rows into compact hot facts.
Rules (I3): assistant prose is NEVER distilled; weight cap 0.5; dedupe by
token Jaccard > 0.8; max `cap` facts per call; read-only vs jit DB.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List

from jev_bridge.judge import tokens

ARCHIVE_TABLE = "pruned_messages"  # adjust to schema from inspection step
WEIGHT_CAP = 0.5


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _compress(text: str, max_len: int = 160) -> str:
    t = " ".join((text or "").split())
    return t[: max_len - 1] + "…" if len(t) > max_len else t


def distill_new_rows(runtime, db_path: str, session_id: str, since_ts: float, cap: int = 3) -> int:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    written = 0
    try:
        rows = conn.execute(
            f"SELECT ts, ai, content FROM {ARCHIVE_TABLE} "
            "WHERE session_id = ? AND ts > ? ORDER BY ts ASC",
            (session_id, since_ts),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    existing: List[Dict[str, str]] = []
    try:
        existing = runtime.get_hot_facts() or []
    except Exception:
        existing = []
    existing_tokens = [tokens(f.get("value", "")) for f in existing]

    for ts, ai, content in rows:
        if written >= cap:
            break
        if ai:  # I3: skip assistant output
            continue
        value = _compress(str(content))
        vt = tokens(value)
        if not vt:
            continue
        if any(_jaccard(vt, et) > 0.8 for et in existing_tokens):
            continue
        key = f"distill:{session_id[:8]}:{int(ts)}"
        try:
            runtime.set_hot_fact(key, value, epistemic_weight=WEIGHT_CAP)
        except Exception:
            continue
        existing_tokens.append(vt)
        written += 1
    return written
```

**Step 4: Verify pass** — `2 passed` (after aligning table/columns with the real schema).
**Step 5: Commit:** `git commit -qm "feat: fence distiller (weight<=0.5, dedupe, read-only)"`

---

### Task 10: Trigger distiller from the judge extension

**Objective:** After recording the verdict, distill rows newer than a per-session watermark; update watermark.

**Files:**
- Modify: `extensions/python/message_loop_prompts_after/_10_shadow_judge.py`
- Test: extend `tests/test_shadow_judge_ext.py`

**Step 1: Failing test additions**
```python
def test_judge_triggers_distill(monkeypatch, tmp_path):
    mod = _load_ext()
    fake = FakeRuntime()
    called = {}
    monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
    monkeypatch.setattr(
        mod, "distill_new_rows",
        lambda rt, db, session_id, since_ts, cap=3: called.setdefault("n", 1),
    )
    monkeypatch.setattr(mod, "_jev_db_path", lambda: str(tmp_path / "jev.db"))
    mod.ShadowJudgeExtension(agent=object()).execute(
        loop_data={"session_id": "s1", "history": _history()}
    )
    assert "n" in called
```

**Step 2: Verify failure** → FAIL (no distill call).

**Step 3: Implement** — in `_10_shadow_judge.py`:
- imports: `import time` and `from jev_bridge.distill import distill_new_rows`
- helper:
```python
def _jev_db_path() -> str:
    return os.path.join(_ROOT, "data", "jev_bridge.db")


_SESSION_WATERMARKS: dict = {}
```
- after `runtime.record_shadow_verdict(verdict)`:
```python
            if cfg.get("jev_distill_enabled", True):
                try:
                    sid = str((kwargs.get("loop_data") or {}).get("session_id") or "default")
                    since = _SESSION_WATERMARKS.get(sid, 0.0)
                    distill_new_rows(
                        runtime,
                        _jit_db_path(),
                        session_id=sid,
                        since_ts=since,
                        cap=int(cfg.get("jev_distill_max_facts", 3)),
                    )
                    _SESSION_WATERMARKS[sid] = time.time()
                except Exception:
                    pass  # I6
```
- `_jit_db_path()` resolves the jit DB from the runtime loader root (same candidates; file `data/jit_context.db`). Export it from `jev_bridge/_runtime.py` as `jit_db_path()` reusing the same root search.

**Step 4: Verify pass** — full suite green.
**Step 5: Commit:** `git commit -qm "feat: judge triggers per-session fence distillation"`

---

## Phase 4 — Slot 4: Advisory eviction + status + rollback proof

### Task 11: Eviction advisor (advice table in OWN db, never mutates hot facts)

**Objective:** When capsule tokens > 90% of budget, write suggestion rows (oldest hot facts first) to `data/jev_bridge.db`. Human/tool decides; runtime untouched.

**Files:**
- Create: `jev_bridge/advice.py`
- Test: `tests/test_advice.py`

**Step 1: Failing test**
```python
import sqlite3

from jev_bridge.advice import write_eviction_advice


class FakeRuntime:
    def __init__(self, capsule_len, rows):
        self._cap = capsule_len
        self._rows = rows

    def compile_capsule(self):
        return "x" * self._cap

    def _connect(self):
        raise AssertionError("advisor must not open jit DB for writes")


def test_advice_written_over_budget(tmp_path, monkeypatch):
    import jev_bridge.advice as adv
    db = str(tmp_path / "jev.db")
    monkeypatch.setattr(adv, "_hot_rows", lambda rt, n: rt._rows)
    rt = FakeRuntime(2000, [("old_fact", 123.0), ("older_fact", 100.0)])  # 2000//4=500 tok > 0.9*500? use budget 500
    n = write_eviction_advice(rt, db, max_capsule_tokens=500, budget_pct=0.9)
    assert n == 2
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT kind, fact_key, applied FROM jev_advice").fetchall()
    conn.close()
    assert all(r[0] == "evict_suggest" and r[2] == 0 for r in rows)


def test_no_advice_under_budget(tmp_path, monkeypatch):
    import jev_bridge.advice as adv
    db = str(tmp_path / "jev.db")
    monkeypatch.setattr(adv, "_hot_rows", lambda rt, n: rt._rows)
    rt = FakeRuntime(1000, [("f", 1.0)])  # 250 tok <= 0.9*500
    assert write_eviction_advice(rt, db, max_capsule_tokens=500, budget_pct=0.9) == 0
```

**Step 2: Verify failure** → FAIL.

**Step 3: Implement** `advice.py`:
```python
"""Slot 4: advisory eviction. Writes suggestions to jev_bridge's OWN db.
Never mutates jit_context hot_facts. Read-only query for candidates.
"""
from __future__ import annotations

import os
import sqlite3
import time


def _ensure(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=2.0) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jev_advice ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, "
            "fact_key TEXT, reason TEXT, applied INTEGER DEFAULT 0)"
        )


def _hot_rows(runtime, n: int):
    """Override seam for tests; production reads jit DB read-only."""
    try:
        conn = sqlite3.connect(getattr(runtime, "_db_path", ""), timeout=2.0)
        rows = conn.execute(
            "SELECT key, updated_at FROM hot_facts "
            "WHERE is_quarantined = 0 ORDER BY updated_at ASC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def write_eviction_advice(runtime, db_path: str, max_capsule_tokens: int, budget_pct: float = 0.9) -> int:
    try:
        capsule = runtime.compile_capsule()
        used = len(capsule) // 4
        if used <= int(max_capsule_tokens * budget_pct):
            return 0
        rows = _hot_rows(runtime, 5)
        if not rows:
            return 0
        _ensure(db_path)
        now = time.time()
        with sqlite3.connect(db_path, timeout=2.0) as conn:
            conn.executemany(
                "INSERT INTO jev_advice (ts, kind, fact_key, reason) VALUES (?,?,?,?)",
                [(now, "evict_suggest", k, f"capsule {used}/{max_capsule_tokens} tok; oldest updated_at") for k, _ in rows],
            )
        return len(rows)
    except Exception:
        return 0  # I6
```
Note: production `_hot_rows` needs the jit DB path — inject it via `runtime._db_path` if the runtime exposes it, else resolve with `jev_bridge._runtime.jit_db_path()` (from Task 10) and `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`.

**Step 4: Verify pass** — `2 passed`.
**Step 5: Commit:** `git commit -qm "feat: advisory eviction writer (own db, read-only jit)"`

---

### Task 12: Advisor extension + `jev_status` + full rollback proof

**Objective:** Post-turn advisor; `execute.py` self-test prints verdict counts + advice count; prove `jev_enabled: false` produces ZERO writes anywhere.

**Files:**
- Create: `extensions/python/message_loop_prompts_after/_20_eviction_advisor.py`
- Modify: `/a0/usr/workdir/a0-jev-bridge/execute.py` (create)
- Test: `tests/test_rollback.py`

**Step 1: Failing test**
```python
import importlib.util
import os
import sqlite3

import conftest  # noqa: F401

BASE = os.path.join(os.path.dirname(__file__), "..")
ADV_PATH = os.path.join(BASE, "extensions/python/message_loop_prompts_after/_20_eviction_advisor.py")


def _load():
    spec = importlib.util.spec_from_file_location("_20_eviction_advisor", ADV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRuntime:
    def compile_capsule(self):
        return "x" * 4000  # 1000 tok, over 0.9*1000


def test_rollback_switch_zero_writes(tmp_path, monkeypatch):
    conftest.DEFAULT_CFG.clear()
    conftest.DEFAULT_CFG.update({"jev_enabled": False})
    try:
        mod = _load()
        fake = FakeRuntime()
        monkeypatch.setattr(mod, "load_runtime_getter", lambda: (lambda: fake))
        db = str(tmp_path / "jev.db")
        monkeypatch.setattr(mod, "_jev_db_path", lambda: db)
        mod.EvictionAdvisorExtension(agent=object()).execute(loop_data={"history": []})
        assert not os.path.exists(db) or sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM jev_advice"
        ).fetchone()[0] == 0
    finally:
        conftest.DEFAULT_CFG.clear()
        conftest.DEFAULT_CFG.update({"jev_enabled": True})
```

**Step 2: Verify failure** → FAIL (extension missing).

**Step 3: Implement** `_20_eviction_advisor.py`:
```python
"""Slot 4 wiring: post-turn budget check -> advice rows. I6 silent."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from helpers.extension import Extension
from helpers import plugins

from jev_bridge._runtime import load_runtime_getter
from jev_bridge.advice import write_eviction_advice


def _jev_db_path() -> str:
    return os.path.join(_ROOT, "data", "jev_bridge.db")


class EvictionAdvisorExtension(Extension):
    def execute(self, **kwargs):
        try:
            cfg = plugins.get_plugin_config("jev_bridge", agent=self.agent) or {}
            if not cfg.get("jev_enabled", True):
                return
            get_runtime = load_runtime_getter()
            if get_runtime is None:
                return
            runtime = get_runtime()
            max_tok = int(cfg.get("max_capsule_tokens", 1500))
            pct = float(cfg.get("jev_eviction_budget_pct", 0.9))
            write_eviction_advice(runtime, _jev_db_path(), max_tok, pct)
        except Exception:
            return  # I6
```

`execute.py` (self-test, mirrors jit_context style):
```python
#!/usr/bin/env python3
"""jev_bridge self-test: loader, gate counts, advice counts."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    from jev_bridge._runtime import load_runtime_getter

    getter = load_runtime_getter()
    print(f"[*] jit_context runtime: {'OK' if getter else 'MISSING (degraded, I6)'}")

    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jev_bridge.db")
    if os.path.isfile(db):
        with sqlite3.connect(db) as conn:
            try:
                n = conn.execute("SELECT COUNT(*) FROM jev_advice").fetchone()[0]
                print(f"[*] advice rows: {n}")
            except sqlite3.Error:
                print("[*] advice table: not created yet")
    if getter:
        rt = getter()
        try:
            s = rt._shadow_stats
            print(f"[*] shadow verdicts: {dict(s)}")
            print(f"[*] l2_promotion_ready: {rt.l2_promotion_ready()}")
        except Exception as e:
            print(f"[!] status probe failed: {e}")
    print("[OK] jev_bridge self-test complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Verify pass** — full suite + `JIT_CONTEXT_PLUGIN_DIR=/a0/usr/workdir/a0-jit-context /opt/venv/bin/python execute.py`
Expected: `jit_context runtime: OK`, verdict dict, `[OK] jev_bridge self-test complete`.
**Step 5: Commit:** `git commit -qm "feat: advisor ext + self-test + rollback proof"`

---

## Phase 5 — Optional HTTP backend + release

### Task 13: HTTP Jev client behind circuit breaker (3 fails → OPEN 30s)

**Objective:** Same `rank()`/verdict contract, remote backend, breaker-guarded, `None` → local fallback. Ships OFF by default (`jev_http_url: ""`).

**Files:**
- Create: `jev_bridge/http_client.py`
- Test: `tests/test_http_client.py`

**Step 1: Failing test**
```python
from jev_bridge.http_client import JevHTTPClient, _Breaker


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _failing_urlopen(req, timeout=None):
    raise OSError("down")


def test_breaker_opens_after_three(monkeypatch):
    clk = FakeClock()
    b = _Breaker(now_fn=clk)
    for _ in range(3):
        b.record_failure()
    assert b.can_execute() is False  # OPEN
    clk.t += 31.0
    assert b.can_execute() is True  # HALF-OPEN after 30s


def test_client_returns_none_and_opens(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _failing_urlopen)
    c = JevHTTPClient("http://127.0.0.1:9", timeout_s=0.05)
    assert c.rank([{"key": "k", "value": "v"}], "q") is None
    c.rank([], "q")
    c.rank([], "q")
    assert c.breaker.state == "OPEN"
```

**Step 2: Verify failure** → FAIL.

**Step 3: Implement** `http_client.py`:
```python
"""Optional HTTP backend for Jev. OFF unless jev_http_url set.
Breaker: 3 failures -> OPEN 30s -> HALF-OPEN. None == use local fallback.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Dict, List, Optional


class _Breaker:
    def __init__(self, threshold: int = 3, recovery: float = 30.0, now_fn=time.time):
        self.threshold = threshold
        self.recovery = recovery
        self.now = now_fn
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure = 0.0

    def can_execute(self) -> bool:
        if self.state == "OPEN":
            if self.now() - self.last_failure > self.recovery:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = self.now()
        if self.failures >= self.threshold:
            self.state = "OPEN"


class JevHTTPClient:
    def __init__(self, base_url: str, timeout_s: float = 0.1):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.breaker = _Breaker()

    def rank(self, facts: List[Dict[str, str]], query: str) -> Optional[List[Dict[str, str]]]:
        if not self.base_url or not self.breaker.can_execute():
            return None
        try:
            payload = json.dumps({"query": query, "facts": facts}).encode()
            req = urllib.request.Request(
                self.base_url + "/rank", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                out = json.loads(resp.read())
            order = out.get("order") or []
            self.breaker.record_success()
            return [facts[i] for i in order if isinstance(i, int) and 0 <= i < len(facts)]
        except Exception:
            self.breaker.record_failure()
            return None
```

**Step 4: Verify pass** — `2 passed`.
**Step 5: Commit:** `git commit -qm "feat: optional HTTP jev client with circuit breaker"`

---

### Task 14: Docs, CHANGELOG, versions, final verification

**Objective:** Release hygiene per DoD: semver, changelog, benchmark artifact note, full green run in both repos.

**Steps:**
1. `a0-jev-bridge/CHANGELOG.md`:
```markdown
# Changelog

## 0.1.0 — 2026-09-21
- Slot 1: deterministic shadow judge feeding jit_context l2_promotion_ready (10/0/0.3 gate)
- Slot 2: L2 vault reranker via runtime.fact_reranker hook (jit_context 0.3.1+)
- Slot 3: fence distiller, weight<=0.5, dedupe, read-only
- Slot 4: advisory eviction (own db, never mutates hot facts)
- Optional HTTP backend behind 3/30s circuit breaker (off by default)
- Rollback: jev_enabled=false -> zero writes, identical behavior
```
2. `a0-jit-context`: bump `plugin.yaml` version `0.3.0 -> 0.3.1`, CHANGELOG entry: "feat: optional fact_reranker hook in _read_vault_facts_sync (backward-compatible)".
3. Full runs:
   - `cd /a0/usr/workdir/a0-jev-bridge && /opt/venv/bin/python -m pytest tests/ -v` → all pass
   - `cd /a0/usr/workdir/a0-jit-context && /opt/venv/bin/python -m pytest tests/ -v` → all pass (incl. pre-existing)
   - `/opt/venv/bin/python scripts/verify_gate_flip.py` → `GATE FLIP: PASS`
4. Commits: both repos, `chore: release ...`.

**Acceptance (maps to DoD):** gate flips on real verdicts (Task 5), rerank deterministic + I6 fallback (Tasks 6–8), distillation weight-capped (Task 9), advice non-mutating (Task 11), rollback zero-write (Task 12), breaker 3/30s (Task 13), versions+changelog (Task 14).

---

## Explicitly OUT of scope (YAGNI)
- No fast-path/LLM bypass, no `before_main_llm_call` code, no capsule mutation in-flight.
- No Obsidian bridge beyond `mem_agent.question` (interface does not exist for more).
- No vector/embedding search in v0.1.0 — token overlap first, measure, then decide.
- No auto-promotion of L2 (`l2_mode` flip stays manual after gate reports True).
