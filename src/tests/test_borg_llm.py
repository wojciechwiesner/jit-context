"""Regression tests for the fast Borg LLM used by JIT classification and distillation."""

import json

import pytest

from context import cascade_distiller
from l0 import borg_llm, tool_buffer


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def test_borg_chat_uses_key_in_header_and_parses_response(monkeypatch):
    observed = {}
    monkeypatch.setattr(borg_llm, "get_borg_api_key", lambda: "test-key")

    def respond(url, *, headers, json, timeout):
        observed.update(url=url, headers=headers, payload=json, timeout=timeout)
        return FakeResponse(200, {"choices": [{"message": {"content": '{"ok":true}'}}]})

    monkeypatch.setattr(borg_llm.requests, "post", respond)
    assert (
        borg_llm.call_borg_chat("classify", timeout=3.5, max_tokens=2000, temperature=0.1, json_mode=True)
        == '{"ok":true}'
    )
    assert observed["url"] == "https://llm.borg.tools/v1/chat/completions"
    assert observed["headers"]["Authorization"] == "Bearer test-key"
    assert observed["payload"]["model"] == "gemini-3.1-flash-lite"
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    assert observed["timeout"] == 3.5


def test_borg_chat_fails_explicitly_without_key(monkeypatch):
    monkeypatch.setattr(borg_llm, "get_borg_api_key", lambda: None)
    with pytest.raises(RuntimeError, match="BORG_TOOLS_LLM_TOKEN"):
        borg_llm.call_borg_chat("classify", timeout=3.5, max_tokens=2000, temperature=0.1, json_mode=True)


def test_borg_chat_fails_explicitly_on_http_error(monkeypatch):
    monkeypatch.setattr(borg_llm, "get_borg_api_key", lambda: "test-key")
    monkeypatch.setattr(borg_llm.requests, "post", lambda *a, **kw: FakeResponse(429, {"error": {"code": 429}}))
    with pytest.raises(RuntimeError, match="429"):
        borg_llm.call_borg_chat("classify", timeout=3.5, max_tokens=2000, temperature=0.1, json_mode=True)


def test_classifier_uses_borg_model_and_validates_grounding(monkeypatch):
    text = "User: Napraw TypeError w src/context/cascade_distiller.py."
    captured = {}
    result = {
        "complexity": "direct_fix",
        "confidence": 0.9,
        "critical_elements": ["Napraw TypeError w src/context/cascade_distiller.py"],
        "enhanced_technical_spec": "Fix the observed TypeError.",
        "acceptance_criteria": "TypeError no longer occurs",
        "target_files": ["src/context/cascade_distiller.py"],
        "cascading_impacts": [],
    }

    def classify(prompt, **kwargs):
        captured.update(kwargs)
        return json.dumps(result)

    monkeypatch.setattr(cascade_distiller, "call_borg_chat", classify)
    actual = cascade_distiller.call_llm_classifier(text, trusted_scope="jit-context")
    assert actual["complexity"] == "direct_fix"
    assert actual["target_files"] == ["src/context/cascade_distiller.py"]
    assert captured == {"timeout": 3.5, "max_tokens": 2000, "temperature": 0.1, "json_mode": True}


def test_distiller_preserves_raw_pointer_after_borg_response(monkeypatch, tmp_path):
    captured = {}

    def distill(prompt, **kwargs):
        captured.update(kwargs)
        return "184 passed, 2 failed; confidence=0.1777"

    monkeypatch.setattr(tool_buffer, "call_borg_chat", distill)
    path = tmp_path / "tool.raw"
    result = tool_buffer.llm_distill("184 passed, 2 failed; confidence=0.1777", "status", path)
    assert "confidence=0.1777" in result
    assert str(path) in result
    assert captured == {"timeout": 25, "max_tokens": 4096, "temperature": 0.0, "json_mode": False}
