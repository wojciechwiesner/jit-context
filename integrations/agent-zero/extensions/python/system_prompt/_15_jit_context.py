"""
System Prompt Extension for JIT-Context (v0.3).

Injects the deterministic, prompt-cache optimized JIT Capsule into the
agent system prompt. Robust runtime bootstrap (installed path, env override,
or repo-relative fallback). I6-hardened: silent degradation on any failure.
"""

import os
import sys
import importlib.util

from helpers.extension import Extension
from helpers import plugins
from agent import LoopData

_RUNTIME_MODULE = "usr.plugins.jit_context.helpers.runtime"


def _load_runtime():
    """Resolve the plugin runtime regardless of install location."""
    try:
        from usr.plugins.jit_context.helpers.runtime import get_runtime
        return get_runtime
    except Exception:
        pass
    mod = sys.modules.get(_RUNTIME_MODULE)
    if mod is not None and hasattr(mod, "get_runtime"):
        return mod.get_runtime
    here = os.path.abspath(__file__)
    plugin_root = os.path.abspath(os.path.join(os.path.dirname(here), "..", "..", ".."))
    for base in (
        os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or "",
        "/a0/usr/plugins/jit_context",
        plugin_root,
    ):
        if not base:
            continue
        path = os.path.join(base, "helpers", "runtime.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location(_RUNTIME_MODULE, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[_RUNTIME_MODULE] = mod
            try:
                spec.loader.exec_module(mod)
                return mod.get_runtime
            except Exception:
                sys.modules.pop(_RUNTIME_MODULE, None)
                return None
    return None


class JITContextExtension(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return
        try:
            config = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if config.get("mode", "active") == "disabled":
                return

            get_runtime = _load_runtime()
            if get_runtime is None:
                return

            runtime = get_runtime()
            capsule = runtime.compile_capsule(agent=self.agent, config=config)
            if capsule and isinstance(system_prompt, list):
                system_prompt.append(capsule)
        except Exception:
            return  # I6: zero-block degradation
