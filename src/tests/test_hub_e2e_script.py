"""scripts/hub_e2e.sh must keep passing: it isolates HOME itself, so the test only supplies the interpreter."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hub_e2e.sh"
TIMEOUT_SECONDS = 180


@pytest.mark.skipif(not all(shutil.which(tool) for tool in ("bash", "git", "node", "curl")),
                    reason="needs bash, git, node and curl")
def test_hub_e2e_script_exits_zero():
    env = dict(os.environ, PY=sys.executable)
    result = subprocess.run(["bash", str(SCRIPT)], cwd=REPO, env=env, capture_output=True, text=True,
                            timeout=TIMEOUT_SECONDS)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "hub e2e OK" in result.stdout
    assert "version changed:" in result.stdout
