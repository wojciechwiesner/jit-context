"""
L2 Prefetch Extension for JIT-Context (v0.3).

Schedules a single background vault prefetch per agent lifetime at agent_init.
agent_init is invoked synchronously from within the async message() loop,
so asyncio.get_running_loop() is available and create_task() is safe.

The prefetch respects the circuit breaker and the 600ms L2 deadline (I6);
failure degrades silently to the local hot path.
"""

import os
import sys
import asyncio
import importlib.util

from helpers.extension import Extension
from helpers import plugins

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


class PrefetchL2Extension(Extension):
    def execute(self, **kwargs):
        try:
            if not self.agent:
                return

            config = plugins.get_plugin_config("jit_context", agent=self.agent) or {}
            if config.get("mode", "active") == "disabled":
                return
            if not config.get("l2_enabled", True):
                return

            get_runtime = _load_runtime()
            if get_runtime is None:
                return
            runtime = get_runtime()

            loop = asyncio.get_running_loop()
            task = loop.create_task(runtime.prefetch_l2(config))
            # Reference on the runtime so the task is never garbage-collected
            runtime._prefetch_task = task
        except RuntimeError:
            # No running event loop (defensive; agent_init runs inside message())
            return
        except Exception:
            return  # I6: never block agent init
