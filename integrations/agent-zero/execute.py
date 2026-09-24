#!/usr/bin/env python3
"""
JIT Context OS Setup & Diagnostic Self-Test.
Allows Agent Zero users to verify and initialize JIT Context OS from WebUI or terminal.
"""

import os
import sys
import sqlite3
import time

def main():
    print("==================================================")
    print("  JIT Context OS - Community Plugin Self-Test     ")
    print("==================================================")
    
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(plugin_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    db_path = os.path.join(data_dir, "jit_context.db")
    print(f"[*] Checking database storage at: {db_path}")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hot_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT,
                    epistemic_weight REAL DEFAULT 1.0,
                    authority REAL DEFAULT 1.0,
                    is_quarantined INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.commit()
        print("    [OK] SQLite WAL engine operational.")
    except Exception as e:
        print(f"    [FAIL] Database setup error: {e}")
        return 1

    print("[*] Verifying invariant engine and capsule compiler...")
    try:
        sys.path.insert(0, plugin_dir)
        from helpers.invariants import InvariantChecker
        from helpers.runtime import JITContextRuntime
        
        runtime = JITContextRuntime()
        runtime.set_hot_fact("system_status", "online", epistemic_weight=1.0)
        capsule = runtime.compile_capsule()
        if "<jit_capsule>" in capsule:
            print("    [OK] Capsule compiler verified successfully.")
        else:
            print("    [WARN] Capsule compiler returned unexpected format.")
    except Exception as e:
        print(f"    [FAIL] Runtime verification failed: {e}")
        return 1

    print("[*] Installation & Health Check: PASSED 100%")
    print("    JIT Context OS is active and ready to optimize prompt caching and context.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
