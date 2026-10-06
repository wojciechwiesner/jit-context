"""Tests for JIT Local Edge Worker."""

import pytest
from pathlib import Path
from unittest.mock import patch
from worker.local_agent import build_workspace_capsule, run_local_worker

def test_build_workspace_capsule(tmp_path):
    # Create sample files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    auth_file = src_dir / "auth.py"
    auth_file.write_text("class Authenticator:\n    def login(self): pass\n", encoding="utf-8")
    
    other_file = src_dir / "utils.py"
    other_file.write_text("def helper(): pass\n", encoding="utf-8")
    
    capsule, evidence = build_workspace_capsule(tmp_path, "Fix bug in login method in auth.py")
    assert "auth.py" in evidence["top_file"]
    assert "<ONA_CONTEXT" in capsule
    assert "class Authenticator:" in capsule

def test_run_local_worker_mock_flow(tmp_path):
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
    
    test_file = tmp_path / "test_calc.py"
    test_file.write_text("from calc import add\ndef test_add(): assert add(2, 3) == 5\n", encoding="utf-8")

    # Mock Ollama call: Turn 1 patch, Turn 2 run_tests
    call_idx = 0
    def mock_ollama(messages, model):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return {
                "message": {"role": "assistant"},
                "content": "",
                "thinking": "Applying patch",
                "tool_calls": [{
                    "id": "tc1",
                    "function": {
                        "name": "patch",
                        "arguments": {
                            "path": "calc.py",
                            "old_string": "    return a * b",
                            "new_string": "    return a + b"
                        }
                    }
                }],
                "latency_s": 0.1,
                "tokens": 50
            }
        else:
            return {
                "message": {"role": "assistant"},
                "content": "",
                "thinking": "Verifying tests",
                "tool_calls": [{
                    "id": "tc2",
                    "function": {
                        "name": "run_tests",
                        "arguments": {"cmd": f"pytest {test_file}"}
                    }
                }],
                "latency_s": 0.1,
                "tokens": 30
            }

    with patch("worker.local_agent.call_ollama_v1", side_effect=mock_ollama):
        res = run_local_worker(
            task="Fix multiplication in add in calc.py",
            workspace_dir=tmp_path,
            test_cmd=f"pytest {test_file}",
            model="lfm2.5:2.6b-64k",
            max_turns=3,
            verbose=False
        )

    assert res["success"] is True
    assert res["patches_applied"] == 1
    assert "return a + b" in target.read_text(encoding="utf-8")
