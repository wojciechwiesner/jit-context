import os
import sys
import types

DEFAULT_CFG = {"jev_enabled": True}


def _stub_framework():
    if "helpers.extension" in sys.modules:
        return
    helpers = types.ModuleType("helpers")
    # Make the stub behave like the real package so `helpers.runtime`
    # and `helpers.invariants` resolve from the repo directory.
    helpers.__path__ = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "helpers"))
    ]
    ext = types.ModuleType("helpers.extension")

    class Extension:
        def __init__(self, agent=None, **kw):
            self.agent = agent

    ext.Extension = Extension
    plugins = types.ModuleType("helpers.plugins")
    plugins.get_plugin_config = lambda name, agent=None: dict(DEFAULT_CFG)
    sys.modules.update({
        "helpers": helpers,
        "helpers.extension": ext,
        "helpers.plugins": plugins,
    })


_stub_framework()
