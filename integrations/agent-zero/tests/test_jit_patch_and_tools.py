"""
Unit tests for JIT-Context Tool Parser, AST Pre-Flight Gate, and Patch Invariant (I10).
"""

import pytest
import os
import sys

# Ensure helpers are importable
HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "helpers"))
if HELPERS_DIR not in sys.path:
    sys.path.insert(0, HELPERS_DIR)

from tool_parser import NativeToolParser, PatchValidator
from invariants import InvariantChecker, EpistemicInvariantError
from runtime import JITContextRuntime


def test_parse_liquid_ai_tool_calls():
    raw_lfm = "<|tool_call_start|>[read_file(path='astropy/separable.py'), grep_code(pattern='def separability_matrix')]<|tool_call_end|>"
    calls = NativeToolParser.parse_calls(raw_lfm)
    assert len(calls) == 2
    assert calls[0]["name"] == "read_file"
    assert calls[0]["arguments"]["path"] == "astropy/separable.py"
    assert calls[0]["format"] == "liquid_native"
    assert calls[1]["name"] == "grep_code"
    assert calls[1]["arguments"]["pattern"] == "def separability_matrix"


def test_parse_xml_tool_calls():
    raw_xml = '<tool_call>{"name": "submit_patch", "arguments": {"file": "foo.py"}}</tool_call>'
    calls = NativeToolParser.parse_calls(raw_xml)
    assert len(calls) == 1
    assert calls[0]["name"] == "submit_patch"
    assert calls[0]["arguments"]["file"] == "foo.py"


def test_patch_validator_valid():
    valid_diff = """diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py
--- a/astropy/modeling/separable.py
+++ b/astropy/modeling/separable.py
@@ -120,4 +120,6 @@ def is_separable(transform):
-    return False
+    return True
"""
    is_valid, msg, modified = PatchValidator.validate_patch(valid_diff)
    assert is_valid is True
    assert "astropy/modeling/separable.py" in modified


def test_patch_validator_ast_check():
    valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    is_valid, err = PatchValidator.validate_python_code(valid_code)
    assert is_valid is True
    assert err is None

    broken_code = "def broken(:\n  return"
    is_valid, err = PatchValidator.validate_python_code(broken_code)
    assert is_valid is False
    assert "SyntaxError" in err


def test_invariant_i10_patch_precedence():
    valid_patch = "diff --git a/file.py b/file.py\n@@ -1 +1 @@\n-a\n+b"
    ok, _ = InvariantChecker.check_patch_artifact_precedence(valid_patch)
    assert ok is True

    invalid_patch = "just a comment without hunks"
    ok, msg = InvariantChecker.check_patch_artifact_precedence(invalid_patch)
    assert ok is False


def test_capsule_compiler_with_patch_artifact():
    rt = JITContextRuntime()
    patch_sample = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new"
    capsule = rt.compile_capsule(config={"patch_artifact": patch_sample})
    
    assert "<invariant id=\"I10\">" in capsule
    assert "<patch_artifact format=\"unified_diff\">" in capsule
    assert patch_sample in capsule
    assert "</patch_artifact>" in capsule
