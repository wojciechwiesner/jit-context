"""H16 chat UI: the cockpit served at /hub/<slug> carries the hub chat config; real generator, real HTTP."""

import json
import re
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import refresher, registry

META_RE = re.compile(r'<meta name="(jit-hub-[a-z]+)" content="([^"]*)">')
HUB_COCKPIT_ID = 'id="chat-hub-panel"'
OLD_BRIDGE_MARKERS = ("X-Cockpit-Token", "Most czatu nie został uruchomiony", "chatRuntime")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is needed for the cockpit generator")


def make_repo(path: Path) -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text("# State\n\n## Tasks\n- [ ] H16 chat ui\n", encoding="utf-8")
    (path / ".gitignore").write_text(".planning/state.html\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "first commit"]):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(config.COCKPIT_BUILDER_ENV, raising=False)
    entry, _ = registry.register_project(make_repo(tmp_path / "chat-demo"))
    result = refresher.refresh_project(entry, force=True)
    assert result.status == refresher.REBUILT, result.detail
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{httpd.server_address[1]}", "entry": entry}
    httpd.shutdown()
    httpd.server_close()


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8")


def test_cockpit_from_hub_carries_chat_config(served):
    slug = served["entry"]["slug"]
    status, html = fetch(f"{served['base']}/hub/{slug}")
    assert status == 200 and HUB_COCKPIT_ID in html
    head = html[html.index("<head>"):html.index("</head>")]
    metas = dict(META_RE.findall(head))
    assert metas[hub_routes.CHAT_META_NAME] == hub_routes.CHAT_ROUTE
    assert metas[hub_routes.SLUG_META_NAME] == slug
    assert metas[hub_routes.CSRF_META_NAME] == hub_routes.csrf_token()
    for marker in OLD_BRIDGE_MARKERS:
        assert marker not in html
    # the endpoint announced to the page answers for the announced slug (empty history, nothing invented)
    status, body = fetch(f"{served['base']}{metas[hub_routes.CHAT_META_NAME]}?slug={metas[hub_routes.SLUG_META_NAME]}")
    payload = json.loads(body)
    assert status == 200 and payload["slug"] == slug and payload["messages"] == []


def test_file_cockpit_has_no_chat_config_but_links_to_the_hub_chat(served):
    slug = served["entry"]["slug"]
    disk_copy = refresher.hub_cockpit_path(slug)
    if not disk_copy.is_file():
        disk_copy = Path(served["entry"]["path"]) / ".planning" / "state.html"
    html = disk_copy.read_text(encoding="utf-8")
    assert META_RE.search(html) is None
    assert f'id="chat-open-hub" href="http://127.0.0.1:8767/hub/{slug}#chat"' in html


def test_chat_meta_escapes_the_slug():
    meta = hub_routes.chat_meta('a"<b>')
    assert 'content="a&quot;&lt;b&gt;"' in meta and '<b>' not in meta
