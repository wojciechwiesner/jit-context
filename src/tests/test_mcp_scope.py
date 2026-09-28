"""MCP server scope isolation: a project must never receive another project's capsule."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("JIT_L0_DB_PATH", str(tmp_path / "overlay.db"))
    import mcp_server

    return importlib.reload(mcp_server)


def test_observatory_query_uses_project_param(mcp, monkeypatch):
    seen = {}

    class Resp:
        status = 200

        def read(self):
            return b'{"scope": "boocco", "capsule": "<C/>"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return Resp()

    monkeypatch.setattr(mcp.urllib.request, "urlopen", fake_urlopen)
    assert mcp.tool_get_jit_context(scope="boocco") == "<C/>"
    assert "project=boocco" in seen["url"]


def test_foreign_scope_capsule_is_rejected(mcp, monkeypatch):
    monkeypatch.setattr(
        mcp, "_call_observatory_live_context", lambda **kw: {"scope": "thesaiver", "capsule": "<FOREIGN/>"}
    )
    mcp.tool_record_jit_observation(fact="Boocco runs on Next.js", scope="boocco", source="t")
    out = mcp.tool_get_jit_context(scope="boocco")
    assert "<FOREIGN/>" not in out
    assert "Boocco runs on Next.js" in out


def test_fallback_reads_only_requested_scope(mcp, monkeypatch):
    monkeypatch.setattr(mcp, "_call_observatory_live_context", lambda **kw: None)
    mcp.tool_record_jit_observation(fact="A uses FastAPI", scope="proj-a", source="t")
    mcp.tool_record_jit_observation(fact="B uses Next.js", scope="proj-b", source="t")
    out = mcp.tool_get_jit_context(scope="proj-a")
    assert "FastAPI" in out and "Next.js" not in out


def test_fallback_ignores_unscoped_hermes_overlay_table(mcp, monkeypatch):
    monkeypatch.setattr(mcp, "_call_observatory_live_context", lambda **kw: None)
    conn = sqlite3.connect(str(mcp.L0_DB_PATH))
    conn.execute("CREATE TABLE overlay (seq INTEGER, kind TEXT, key TEXT, value TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO overlay VALUES (1, 'statement', 'user_utterance', 'SECRET other chat', 'active', '')")
    conn.commit()
    conn.close()
    assert "SECRET" not in mcp.tool_get_jit_context(scope="proj-a")
