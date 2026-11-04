"""Hub project chat: POST /api/hub/chat {slug, messages} -> reply grounded in the project's files.

The server owns the system prompt (hub.chat_prompt); the client sends only user/assistant turns. The reply is
returned in one piece (no streaming). Upstream failures become explicit errors: 504 on timeout, 502 otherwise,
always with the upstream HTTP status (or null) and the source list; there is no canned fallback answer.
The last user message and the reply (or the error) are appended to the project's history file.
"""

from __future__ import annotations

import json
import threading
import time
from typing import List, Optional, Tuple

from hub import chat_history, chat_prompt, chat_upstream

MAX_MESSAGES = 40
MAX_MESSAGE_CHARS = 20000
ALLOWED_ROLES = ("user", "assistant")
MAX_CONCURRENT_CHATS = 2
GATEWAY_ERROR = 502
GATEWAY_TIMEOUT = 504
BUSY = 429

_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_CHATS)


class ChatRequestError(ValueError):
    """The client sent an unusable request (HTTP 400)."""


def parse_request(body: bytes) -> Tuple[str, List[dict]]:
    """(slug, messages) from the JSON body, or ChatRequestError with the reason."""
    try:
        payload = json.loads(body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChatRequestError(f"treść żądania nie jest JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ChatRequestError("oczekiwano obiektu JSON {slug, messages}")
    slug, messages = payload.get("slug"), payload.get("messages")
    if not isinstance(slug, str) or not slug:
        raise ChatRequestError("brak pola slug")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise ChatRequestError(f"messages musi być listą 1..{MAX_MESSAGES} wiadomości")
    cleaned = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in ALLOWED_ROLES:
            raise ChatRequestError(f"każda wiadomość musi mieć role z {ALLOWED_ROLES}")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_MESSAGE_CHARS:
            raise ChatRequestError(f"content musi być niepustym tekstem do {MAX_MESSAGE_CHARS} znaków")
        cleaned.append({"role": item["role"], "content": content})
    if cleaned[-1]["role"] != "user":
        raise ChatRequestError("ostatnia wiadomość musi pochodzić od użytkownika")
    return slug, cleaned


def _error_reply(exc: chat_upstream.UpstreamError, settings: chat_upstream.ChatSettings,
                 sources: List[dict]) -> Tuple[int, dict]:
    code = GATEWAY_TIMEOUT if exc.timeout else GATEWAY_ERROR
    return code, {"error": f"model nie odpowiedział poprawnie: {exc}", "upstream_status": exc.status,
                  "upstream_url": settings.completions_url, "model": settings.model, "sources": sources}


def run_chat(entry: dict, messages: List[dict], settings: Optional[chat_upstream.ChatSettings] = None
             ) -> Tuple[int, dict]:
    """(HTTP status, payload) for one chat turn of a registered project."""
    if not _SLOTS.acquire(blocking=False):
        return BUSY, {"error": f"trwa już {MAX_CONCURRENT_CHATS} rozmów z modelem; spróbuj za chwilę"}
    try:
        settings = settings or chat_upstream.load_settings()
        prompt, sources = chat_prompt.build_system_prompt(entry)
        started = time.monotonic()
        try:
            result = chat_upstream.complete(settings, [{"role": "system", "content": prompt}, *messages])
        except chat_upstream.UpstreamError as exc:
            code, payload = _error_reply(exc, settings, sources)
            chat_history.append(entry["slug"], [
                {"role": "user", "content": messages[-1]["content"]},
                {"role": "error", "content": payload["error"], "upstream_status": exc.status,
                 "http_status": code, "model": settings.model}])
            return code, payload
        elapsed_ms = round((time.monotonic() - started) * 1000)
        chat_history.append(entry["slug"], [
            {"role": "user", "content": messages[-1]["content"]},
            {"role": "assistant", "content": result["reply"], "model": result["model"], "usage": result["usage"],
             "elapsed_ms": elapsed_ms, "sources": [source["name"] for source in sources
                                                   if source["status"] == chat_prompt.STATUS_INCLUDED]}])
        return 200, {"slug": entry["slug"], "reply": result["reply"], "model": result["model"],
                     "model_origin": settings.origin, "usage": result["usage"], "elapsed_ms": elapsed_ms,
                     "prompt_chars": len(prompt), "sources": sources}
    finally:
        _SLOTS.release()
