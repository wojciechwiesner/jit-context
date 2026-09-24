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
    conn.execute(
        "CREATE TABLE pruned_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT, message_index INTEGER, "
        "ai INTEGER, content TEXT, created_at REAL)"
    )
    rows = [
        ("s1", 0, 0, "user wants nginx config for boocco deploy on borg.tools", 1.0),
        ("s1", 1, 1, "assistant long prose that must be ignored entirely", 1.1),
        ("s1", 2, 0, "user wants nginx config for boocco deploy on borg.tools", 1.2),  # dupe
        ("s1", 3, 0, "deadline for invoiceflow KSeF sync is friday", 1.3),
    ]
    conn.executemany(
        "INSERT INTO pruned_history (session_id, message_index, ai, content, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
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
