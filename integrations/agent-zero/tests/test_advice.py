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
    rt = FakeRuntime(2000, [("old_fact", 123.0), ("older_fact", 100.0)])  # 2000//4=500 tok > 0.9*500
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
