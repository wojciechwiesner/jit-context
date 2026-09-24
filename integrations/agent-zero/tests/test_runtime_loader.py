import os

def test_loader_resolves_dev_runtime():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["JIT_CONTEXT_PLUGIN_DIR"] = repo_root
    from jev_bridge._runtime import load_runtime_getter
    get_runtime = load_runtime_getter()
    assert get_runtime is not None
    rt = get_runtime()
    assert hasattr(rt, "record_shadow_verdict")
    assert hasattr(rt, "compile_capsule")

def test_loader_silent_when_missing():
    os.environ["JIT_CONTEXT_PLUGIN_DIR"] = "/nonexistent-xyz"
    import sys
    sys.modules.pop("usr.plugins.jit_context.helpers.runtime", None)
    from jev_bridge._runtime import load_runtime_getter
    # may still find /a0/usr/workdir fallback; must not raise either way
    getter = load_runtime_getter()
    assert getter is None or callable(getter)
