"""Feedby widget keys, generated exactly like Feedby's own issue-widget-key.ts.

Format: `wk_live_` + base64url(32 random bytes). Feedby stores only sha256(plaintext) in
`widget_keys.key_hash`; the plaintext is a public key (it ships in page HTML), but we still keep
it out of chat output and in a chmod 600 local store.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets

WIDGET_KEY_PREFIX = "wk_live_"
SECRET_BYTE_LENGTH = 32
KEY_PATTERN = re.compile(r"^wk_live_[A-Za-z0-9_-]{20,}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def generate_widget_key() -> str:
    random_part = base64.urlsafe_b64encode(secrets.token_bytes(SECRET_BYTE_LENGTH)).decode().rstrip("=")
    return f"{WIDGET_KEY_PREFIX}{random_part}"


def hash_widget_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def mask(plaintext: str) -> str:
    """Display form: prefix + last 4 chars, never the full key."""
    return f"{WIDGET_KEY_PREFIX}...{plaintext[-4:]}"


def is_valid_key(plaintext: str) -> bool:
    return bool(KEY_PATTERN.match(plaintext or ""))
