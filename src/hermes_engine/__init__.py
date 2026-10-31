"""JIT context engine for Hermes (``context.engine: jit``).

It extends Hermes' built-in ``ContextCompressor`` instead of replacing it: emergency
compression, thresholds and summaries behave exactly as with ``engine: compressor``
(settings are parsed by Hermes' own ``_parse_compression_config``). What it adds is
``select_context``: before every provider request, old bulky tool results are
swapped for one-line pointers (see ``selection.py``). The session transcript in
``state.db`` is never modified.

Env vars (so a single run can be tuned without editing config):
  JIT_ENGINE_KEEP_TURNS  user turns whose tool output stays verbatim (default 2)
  JIT_ENGINE_MIN_CHARS   tool results shorter than this are never elided (default 1200)
  JIT_ENGINE_DISABLED=1  pass requests through unchanged (A/B "hook only" arm)
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any

from agent.context_compressor import ContextCompressor

try:  # package import (Hermes plugin loader)
    from .selection import select_wire_messages
except ImportError:  # flat import (tests, snapshot on sys.path)
    from selection import select_wire_messages  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

ENGINE_NAME = "jit"
DEFAULT_MODEL = "unknown"


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def compressor_kwargs_from_config() -> dict[str, Any]:
    """Built-in compressor settings from config.yaml, parsed exactly like Hermes does."""
    try:
        from agent.agent_init import _parse_compression_config
        from hermes_cli.config import load_config_readonly

        settings = _parse_compression_config(SimpleNamespace(model="", api_mode=None), load_config_readonly())
    except Exception as exc:  # fail-open: Hermes defaults
        logger.warning("jit engine: could not read compression config (%s); using defaults", exc)
        return {}
    return dict(
        threshold_percent=settings.threshold,
        protect_first_n=settings.protect_first,
        protect_last_n=settings.protect_last,
        summary_target_ratio=settings.target_ratio,
        abort_on_summary_failure=settings.abort_on_summary_failure,
        model_thresholds=settings.model_thresholds,
        threshold_tokens_cap=settings.threshold_tokens,
        proactive_prune_tokens=settings.proactive_prune_tokens,
        proactive_prune_min_result_chars=settings.proactive_prune_min_chars,
        proactive_prune_min_reclaim_tokens=settings.proactive_prune_min_reclaim,
        min_tail_user_messages=settings.min_tail_users,
        tail_mode=settings.tail_mode,
    )


class JitContextEngine(ContextCompressor):
    """Built-in compressor plus per-request JIT wire selection."""

    def __init__(self, model: str = DEFAULT_MODEL, **kwargs: Any) -> None:
        settings = compressor_kwargs_from_config()
        settings.update(kwargs)
        settings.setdefault("quiet_mode", True)
        super().__init__(model=model, **settings)
        self.selection_count = 0
        self.elided_results = 0

    @property
    def name(self) -> str:
        return ENGINE_NAME

    def select_context(
        self,
        request_messages: list[dict[str, Any]],
        *,
        conversation_messages: list[dict[str, Any]] | None = None,
        incoming_message: dict[str, Any] | None = None,
        budget_tokens: int = 0,
    ) -> list[dict[str, Any]] | None:  # type: ignore[override]  # base returns None too
        if os.environ.get("JIT_ENGINE_DISABLED") == "1":
            return None
        selected, stats = select_wire_messages(
            request_messages,
            keep_recent_turns=_env_int("JIT_ENGINE_KEEP_TURNS", 2),
            min_prune_chars=_env_int("JIT_ENGINE_MIN_CHARS", 1200),
        )
        if stats.pruned_results == 0:
            return None
        self.selection_count += 1
        self.elided_results += stats.pruned_results
        logger.info(
            "jit engine: elided %d tool results, %d -> %d chars (-%d)",
            stats.pruned_results, stats.chars_before, stats.chars_after, stats.chars_saved,
        )
        return selected


def register(ctx: Any) -> None:
    """Hermes plugin entry point: register one engine instance for ``context.engine: jit``."""
    ctx.register_context_engine(JitContextEngine())
