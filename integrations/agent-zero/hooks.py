"""
Framework lifecycle hooks for JIT Context OS (with integrated JEV Bridge).
Executes inside Agent Zero framework runtime.
"""
import os


def install():
    """Called automatically on install/update. Idempotent."""
    print("[JIT Context OS + JEV] post-install setup...")
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(plugin_dir, "data"), exist_ok=True)
    # keep API key if present (never overwrite/remove user data)
    return 0


def pre_update():
    return 0


def uninstall():
    """Stop nothing (no owned processes); caches are inside plugin dir."""
    print("[JIT Context OS + JEV] cleanup...")
    return 0
