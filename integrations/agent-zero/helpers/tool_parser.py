"""
Tool Call & Native Agent Token Parser with Unified Diff & AST Pre-Flight Validator.

Supports:
1. LiquidAI LFM 2.5 Native Tokens: <|tool_call_start|>[call1, call2]<|tool_call_end|>
2. Hermes / XML tool calling: <tool_call>{...}</tool_call>
3. Git Unified Diff extraction and AST Pre-Flight Syntax Gate.
"""

import re
import ast
import json
from typing import Dict, Any, List, Optional, Tuple


class NativeToolParser:
    """Parses model-native tool invocation tokens from Liquid AI, Hermes, and LLM output."""

    LFM_PATTERN = re.compile(r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>", re.DOTALL)
    XML_PATTERN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)

    @classmethod
    def parse_calls(cls, text: str) -> List[Dict[str, Any]]:
        """Extract all tool calls from text into normalized dicts: [{'name': '...', 'arguments': {...}}]."""
        calls: List[Dict[str, Any]] = []
        if not text:
            return calls

        # 1. Check Liquid AI token pattern
        lfm_matches = cls.LFM_PATTERN.findall(text)
        for match in lfm_matches:
            raw_str = match.strip()
            if raw_str.startswith("[") and raw_str.endswith("]"):
                raw_str = raw_str[1:-1]
            # Extract individual function calls like: func(arg='val', ...)
            fn_calls = re.findall(r"([a-zA-Z_0-9]+)\((.*?)\)(?:,\s*|$)", raw_str)
            for fn_name, fn_args_str in fn_calls:
                args = {}
                # Parse key='value' or key="value" pairs
                arg_pairs = re.findall(r"([a-zA-Z_0-9]+)=([\"\'])(.*?)\2", fn_args_str)
                for k, _, v in arg_pairs:
                    args[k] = v
                calls.append({"name": fn_name, "arguments": args, "format": "liquid_native"})

        # 2. Check XML / Hermes format
        xml_matches = cls.XML_PATTERN.findall(text)
        for match in xml_matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, dict) and "name" in data:
                    calls.append({"name": data["name"], "arguments": data.get("arguments", {}), "format": "xml_native"})
            except Exception:
                pass

        return calls

    @classmethod
    def has_tool_calls(cls, text: str) -> bool:
        return bool(cls.LFM_PATTERN.search(text) or cls.XML_PATTERN.search(text))


class PatchValidator:
    """Unified Diff and AST syntax pre-flight validation."""

    HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
    FILE_HEADER_PATTERN = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.MULTILINE)

    @classmethod
    def extract_patch(cls, text: str) -> str:
        """Extract unified diff from code blocks or raw text."""
        if "```diff" in text:
            return text.split("```diff")[1].split("```")[0].strip()
        elif "```patch" in text:
            return text.split("```patch")[1].split("```")[0].strip()
        elif "diff --git" in text:
            return "diff --git" + text.split("diff --git", 1)[1].split("```")[0].strip()
        return text.strip()

    @classmethod
    def validate_patch(cls, patch_text: str) -> Tuple[bool, str, List[str]]:
        """
        Validates unified diff format:
        Returns: (is_valid, error_message, list_of_modified_files)
        """
        if not patch_text:
            return False, "Patch is empty", []

        files = cls.FILE_HEADER_PATTERN.findall(patch_text)
        modified_files = [f[0] for f in files] if files else []

        # Check if diff has hunk headers
        hunks = cls.HUNK_HEADER_PATTERN.findall(patch_text)
        if not hunks and "diff --git" in patch_text:
            return False, "Malformed diff: missing hunk header (@@ -x,y +a,b @@)", modified_files

        return True, "Valid patch structure", modified_files

    @classmethod
    def validate_python_code(cls, code_snippet: str) -> Tuple[bool, Optional[str]]:
        """Validates Python code snippet syntax using standard AST."""
        try:
            ast.parse(code_snippet)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"
