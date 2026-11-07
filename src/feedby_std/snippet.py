"""Render and inject the managed Feedby widget snippet into one mount file.

The snippet lives between `feedby:start` / `feedby:end` markers, so re-running replaces it in place
(idempotent) and removal is a clean cut. Supported mount kinds:
- html  : plain HTML / Jinja / HTML partials (inserted before the last </body>, else appended)
- astro : Astro layouts (scripts marked is:inline so Astro does not bundle them)
- jsx   : React/TSX root layouts (inserted before <Scripts /> or </body>)
"""

from __future__ import annotations

import json
import re
from typing import Optional

SCRIPT_SRC = "https://feedby.borg.tools/v1/feedby.global.js"
MARK_START = "feedby:start"
MARK_END = "feedby:end"
MANAGED_NOTE = "managed by `jit feedby`, public widget key"
KINDS = ("html", "astro", "jsx")

_HTML_BLOCK = re.compile(r"[ \t]*<!-- feedby:start.*?feedby:end -->\n?", re.S)
_JSX_BLOCK = re.compile(r"[ \t]*\{/\* feedby:start.*?feedby:end \*/\}\n?", re.S)


def kind_for(path: str) -> str:
    if path.endswith(".astro"):
        return "astro"
    if path.endswith((".tsx", ".jsx")):
        return "jsx"
    return "html"


def _config_js(widget_key: str, locale: str) -> str:
    config = json.dumps({"widgetKey": widget_key, "locale": locale})
    # Page-level FeedbyConfig (e.g. SSO user) wins over the defaults.
    return f"window.FeedbyConfig=Object.assign({config},window.FeedbyConfig||{{}});"


def render(kind: str, widget_key: str, locale: str = "pl", indent: str = "") -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown mount kind: {kind}")
    config_js = _config_js(widget_key, locale)
    if kind == "jsx":
        # Safe: the inner HTML is our own json.dumps of a validated key + locale, never user input.
        lines = [
            f"{{/* {MARK_START} ({MANAGED_NOTE}) */}}",
            f"<script dangerouslySetInnerHTML={{{{ __html: {json.dumps(config_js)} }}}} />",
            f'<script src="{SCRIPT_SRC}" async />',
            f"{{/* {MARK_END} */}}",
        ]
    else:
        inline = " is:inline" if kind == "astro" else ""
        lines = [
            f"<!-- {MARK_START} ({MANAGED_NOTE}) -->",
            f"<script{inline}>{config_js}</script>",
            f'<script{inline} src="{SCRIPT_SRC}" async></script>',
            f"<!-- {MARK_END} -->",
        ]
    return "".join(f"{indent}{line}\n" for line in lines)


def strip(text: str) -> str:
    return _JSX_BLOCK.sub("", _HTML_BLOCK.sub("", text))


def has_block(text: str) -> bool:
    return MARK_START in text and MARK_END in text


def _anchor(text: str, kind: str) -> Optional[int]:
    """Offset of the line where the block is inserted (start of the anchor line)."""
    anchors = ["<Scripts />", "</body>"] if kind == "jsx" else ["</body>"]
    for anchor in anchors:
        pos = text.rfind(anchor)
        if pos != -1:
            return text.rfind("\n", 0, pos) + 1
    return None


def inject(text: str, kind: str, widget_key: str, locale: str = "pl") -> str:
    """Return text with exactly one managed block. Never touches anything outside the markers."""
    clean = strip(text)
    line_start = _anchor(clean, kind)
    if line_start is None:
        if kind == "jsx":
            raise ValueError("no <Scripts /> or </body> anchor in JSX mount file")
        suffix = "" if clean.endswith("\n") or not clean else "\n"
        return clean + suffix + render(kind, widget_key, locale)
    anchor_line = clean[line_start:]
    anchor_indent = anchor_line[: len(anchor_line) - len(anchor_line.lstrip(" \t"))]
    # JSX: sibling of <Scripts />, same indent. HTML: child of <body>, one level deeper than </body>.
    block_indent = anchor_indent if kind == "jsx" else anchor_indent + "  "
    return clean[:line_start] + render(kind, widget_key, locale, block_indent) + clean[line_start:]
