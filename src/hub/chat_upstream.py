"""OpenAI-compatible chat completion call for the hub chat, and where its settings come from.

Settings, first match wins per key: environment ($JIT_HUB_CHAT_URL, $JIT_HUB_CHAT_MODEL, $JIT_HUB_CHAT_TIMEOUT),
the "chat" object of <hub dir>/config.json, the model of the old cockpit bridge
(<HERMES_HOME>/state/project-cockpit/runtime.json), then the defaults below. An optional bearer key is read from
$JIT_HUB_CHAT_API_KEY only (never from a file). Every failure raises UpstreamError with the upstream HTTP status
when there is one; the caller turns it into an explicit error reply, never into a made-up answer.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import config

URL_ENV = "JIT_HUB_CHAT_URL"
MODEL_ENV = "JIT_HUB_CHAT_MODEL"
TIMEOUT_ENV = "JIT_HUB_CHAT_TIMEOUT"
API_KEY_ENV = "JIT_HUB_CHAT_API_KEY"
DEFAULT_BASE_URL = "http://127.0.0.1:8788/v1"
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_TIMEOUT_SECONDS = 90.0
HUB_CONFIG_FILE = "config.json"
COCKPIT_RUNTIME_FILE = Path("state") / "project-cockpit" / "runtime.json"
COMPLETIONS_PATH = "/chat/completions"
MAX_TOKENS = 1500
TEMPERATURE = 0.2
ERROR_BODY_CHARS = 500


class UpstreamError(Exception):
    """The model endpoint failed: status is its HTTP status, or None (timeout, refused, bad payload)."""

    def __init__(self, message: str, status: Optional[int] = None, timeout: bool = False):
        super().__init__(message)
        self.status = status
        self.timeout = timeout


@dataclass
class ChatSettings:
    base_url: str
    model: str
    timeout: float
    origin: str

    @property
    def completions_url(self) -> str:
        return self.base_url.rstrip("/") + COMPLETIONS_PATH


def _json_file(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def load_settings() -> ChatSettings:
    """Effective chat settings, read per call so a config edit needs no server restart."""
    hub_chat = _json_file(config.hub_dir() / HUB_CONFIG_FILE).get("chat")
    hub_chat = hub_chat if isinstance(hub_chat, dict) else {}
    bridge_model = _json_file(_hermes_home() / COCKPIT_RUNTIME_FILE).get("model")
    model, origin = DEFAULT_MODEL, "domyślny"
    for value, label in ((bridge_model, "project-cockpit/runtime.json"), (hub_chat.get("model"), "hub config.json"),
                         (os.environ.get(MODEL_ENV), MODEL_ENV)):
        if isinstance(value, str) and value.strip():
            model, origin = value.strip(), label
    base_url = os.environ.get(URL_ENV) or hub_chat.get("base_url") or DEFAULT_BASE_URL
    raw_timeout = os.environ.get(TIMEOUT_ENV) or hub_chat.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return ChatSettings(str(base_url), model, timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS, origin)


def _request(settings: ChatSettings, messages: List[dict]) -> urllib.request.Request:
    body = json.dumps({"model": settings.model, "messages": messages, "stream": False,
                       "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(API_KEY_ENV)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return urllib.request.Request(settings.completions_url, data=body, headers=headers, method="POST")


def _reply_text(payload: object) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise UpstreamError(f"odpowiedź bez choices[0].message.content ({type(exc).__name__})") from exc
    if not isinstance(content, str) or not content.strip():
        raise UpstreamError("model zwrócił pustą odpowiedź")
    return content.strip()


def complete(settings: ChatSettings, messages: List[dict]) -> dict:
    """{"reply", "usage", "model"} from the endpoint, or UpstreamError."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback: never via a proxy
    try:
        with opener.open(_request(settings, messages), timeout=settings.timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:ERROR_BODY_CHARS].decode("utf-8", errors="replace")
        raise UpstreamError(f"HTTP {exc.code} z {settings.completions_url}: {detail}", status=exc.code) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise UpstreamError(f"brak odpowiedzi w {settings.timeout:g} s", timeout=True) from exc
    except urllib.error.URLError as exc:
        is_timeout = isinstance(exc.reason, (socket.timeout, TimeoutError))
        message = f"brak odpowiedzi w {settings.timeout:g} s" if is_timeout else f"połączenie nieudane: {exc.reason}"
        raise UpstreamError(message, timeout=is_timeout) from exc
    except OSError as exc:
        raise UpstreamError(f"połączenie przerwane: {type(exc).__name__}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise UpstreamError(f"odpowiedź nie jest JSON: {raw[:ERROR_BODY_CHARS]!r}") from exc
    usage = payload.get("usage") if isinstance(payload, dict) else None
    model = payload.get("model") if isinstance(payload, dict) else None
    return {"reply": _reply_text(payload), "usage": usage, "model": model or settings.model}
