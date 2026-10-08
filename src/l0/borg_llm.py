"""Small OpenAI-compatible client for JIT's fast Borg-hosted LLM tasks."""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

DEFAULT_BASE_URL = "https://llm.borg.tools/v1"
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def get_borg_api_key() -> Optional[str]:
    key = os.environ.get("BORG_TOOLS_LLM_TOKEN")
    if key:
        return key
    env_file = Path.home() / ".hermes" / ".env"
    try:
        for line in env_file.read_text().splitlines():
            if line.startswith("BORG_TOOLS_LLM_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"\'') or None
    except OSError:
        pass
    return None


def call_borg_chat(
    prompt: str,
    *,
    timeout: float,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> str:
    """Return model text or raise a visible error; never invent an LLM response."""
    key = get_borg_api_key()
    if not key:
        raise RuntimeError("BORG_TOOLS_LLM_TOKEN is not configured")
    base_url = os.environ.get("JIT_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("JIT_LLM_BASE_URL must use HTTPS or loopback HTTP")
    payload = {
        "model": os.environ.get("JIT_LLM_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = requests.post(
            base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + key},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Borg LLM request failed: " + type(exc).__name__) from exc
    if response.status_code != 200:
        raise RuntimeError(f"Borg LLM returned HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Borg LLM returned an invalid response") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Borg LLM returned empty text")
    return content
