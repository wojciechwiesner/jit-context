"""Resolve the jit_context runtime across dev/install layouts (I6: None = degrade)."""
from __future__ import annotations

import importlib.util
import os
import sys

_MODULE = "usr.plugins.jit_context.helpers.runtime"


def _candidate_roots():
    yield os.environ.get("JIT_CONTEXT_PLUGIN_DIR") or ""
    yield os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yield "/a0/usr/plugins/jit_context"
    yield "/a0/usr/workdir/a0-jit-context"


def load_runtime_getter():
    try:
        from usr.plugins.jit_context.helpers.runtime import get_runtime
        return get_runtime
    except Exception:
        pass
    mod = sys.modules.get(_MODULE)
    if mod is not None and hasattr(mod, "get_runtime"):
        return mod.get_runtime
    for base in _candidate_roots():
        if not base:
            continue
        path = os.path.join(base, "helpers", "runtime.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(_MODULE, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[_MODULE] = mod
            spec.loader.exec_module(mod)
            return mod.get_runtime
        except Exception:
            sys.modules.pop(_MODULE, None)
            return None
    return None


def jit_db_path():
    for base in _candidate_roots():
        if not base:
            continue
        p = os.path.join(base, "data", "jit_context.db")
        if os.path.isfile(p):
            return p
    return None
