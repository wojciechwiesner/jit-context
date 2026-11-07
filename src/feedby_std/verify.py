"""Live checks for a provisioned repo: key accepted by Feedby, snippet in the mount, page serves it.

The key probe posts an intentionally empty body to /v1/widget/suggest: an unknown key is rejected
with 401 `invalid_widget_key` before body validation, a valid key gets 400 `invalid_body`.
Nothing is written to Feedby.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from feedby_std import snippet

PROBE_URL = "https://feedby-admin.borg.tools/v1/widget/suggest"
PROBE_TIMEOUT_SECONDS = 10
KEY_ACCEPTED = "accepted"
KEY_REJECTED = "rejected"
KEY_UNKNOWN = "unknown"


def probe_key(widget_key: str) -> str:
    request = urllib.request.Request(
        PROBE_URL, data=b"{}", method="POST",
        headers={"content-type": "application/json", "x-feedby-widget-key": widget_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return KEY_ACCEPTED if response.status < 300 else KEY_UNKNOWN
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        if err.code == 401 and "invalid_widget_key" in body:
            return KEY_REJECTED
        if err.code == 400 and "invalid_body" in body:
            return KEY_ACCEPTED
        return KEY_UNKNOWN
    except (urllib.error.URLError, TimeoutError):
        return KEY_UNKNOWN


def mounts_with_block(repo: Path, mounts: List[str]) -> Dict[str, bool]:
    return {rel: snippet.has_block((repo / rel).read_text(encoding="utf-8")) for rel in mounts}


def page_serves_widget(url: str, widget_key: str) -> Optional[bool]:
    """True when the live HTML contains the script tag and this key; None when the page is unreachable."""
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            html = response.read(2_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return snippet.SCRIPT_SRC in html and widget_key in html
