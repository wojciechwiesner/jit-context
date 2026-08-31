"""Performance Benchmark Suite for Hermes JIT Context OS."""

import time
import pytest
from pathlib import Path
from l0.db import get_db, init_db
from l0.overlay import append_event, ensure_session, get_active_overlays
from context.compiler import compile_context

@pytest.fixture
def perf_db(tmp_path):
    db_file = tmp_path / "perf_overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    yield conn
    conn.close()

def test_l0_wal_append_latency(perf_db):
    session_id = "perf_s1"
    ensure_session(perf_db, session_id)
    
    latencies = []
    for i in range(100):
        t0 = time.perf_counter()
        append_event(perf_db, session_id, "user", f"Wydajność test {i}", "direct_user")
        latencies.append((time.perf_counter() - t0) * 1000.0)
        
    p95 = sorted(latencies)[95]
    print(f"\n[L0 Performance] Append p95: {p95:.2f} ms")
    assert p95 < 5.0 # Must stay within low single-digit ms

def test_context_compilation_latency(perf_db):
    session_id = "perf_s2"
    ensure_session(perf_db, session_id)
    append_event(perf_db, session_id, "user", "Wartość klucza X=123", "direct_user")
    
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        capsule = compile_context(perf_db, session_id, "Jaka jest wartość X?")
        latencies.append((time.perf_counter() - t0) * 1000.0)
        assert "123" in capsule
        
    p95 = sorted(latencies)[47]
    print(f"\n[Compiler Performance] Compile p95: {p95:.2f} ms")
    assert p95 < 5.0
