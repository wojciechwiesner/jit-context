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
    assert [f["value"][:14] for f in facts] == [
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
