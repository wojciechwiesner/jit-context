"""Hub UI (GET /hub): page + assets over real HTTP, worktree/dossier fields of the API, node string tests."""

import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from health import hub_routes, livestream
from hub import project_links, registry

HERE = Path(__file__).parent
NODE_RENDER_TEST = HERE / "hub_render.test.js"
GIT = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]


def git(cwd: Path, *args: str) -> None:
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


def make_repo(path: Path, state_md: str = "# State\n\n- [ ] H14 hub ui\n") -> Path:
    (path / ".planning").mkdir(parents=True)
    (path / ".planning" / "STATE.md").write_text(state_md, encoding="utf-8")
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "first commit")
    return path


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv(config.HUB_DIR_ENV, str(tmp_path / "hub"))
    repo = make_repo(tmp_path / "demo")
    git(repo, "worktree", "add", "-q", "-b", "feat/side", str(tmp_path / "demo-wt-side"))
    entry, _ = registry.register_project(repo)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), livestream.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{httpd.server_address[1]}", "slug": entry["slug"], "tmp": tmp_path}
    httpd.shutdown()
    httpd.server_close()


def get(url: str):
    with urllib.request.urlopen(url, timeout=10) as res:
        return res.status, res.headers.get("Content-Type", ""), res.read().decode("utf-8")


def test_hub_page_is_served_with_csrf_and_assets(server):
    status, ctype, html = get(server["base"] + "/hub")
    assert status == 200 and ctype.startswith("text/html")
    assert f'<meta name="{hub_routes.CSRF_META_NAME}" content="{hub_routes.csrf_token()}">' in html
    assert '<script src="/static/hub.js"></script>' in html
    assert '<link rel="stylesheet" href="/static/hub.css">' in html
    assert 'id="hub-rows"' in html and "Otwarte zadania" in html
    assert get(server["base"] + "/hub/")[2] == html


def test_hub_script_fetches_projects_api(server):
    status, ctype, js = get(server["base"] + "/static/hub.js")
    assert status == 200 and ctype.startswith("text/javascript")
    assert 'const PROJECTS_URL = "/api/hub/projects";' in js
    assert "fetch(PROJECTS_URL" in js
    assert ".innerHTML = renderRows(" in js and "function esc(" in js


def test_hub_css_has_dark_and_light_theme(server):
    status, ctype, css = get(server["base"] + "/static/hub.css")
    assert status == 200 and ctype.startswith("text/css")
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css


def test_projects_api_lists_worktrees_and_dossier(server):
    _, _, body = get(server["base"] + "/api/hub/projects")
    row = json.loads(body)["projects"][0]
    assert row["slug"] == server["slug"]
    assert row["worktrees"]["count"] == 1
    item = row["worktrees"]["items"][0]
    assert item["branch"] == "feat/side"
    assert Path(item["path"]).resolve() == (server["tmp"] / "demo-wt-side").resolve()
    assert item["last_commit"]["subject"] == "first commit"
    assert row["dossier"] == {"name": "demo", "note": "projects/demo.md", "source": "nazwa katalogu",
                              "uri": "obsidian://open?vault=Wojciech&file=projects%2Fdemo.md"}


@pytest.mark.parametrize("state_md, jit_json, expected", [
    ("**SSOT w Obsidianie:** `~/Documents/Wojciech/projects/hermes-jit.md`\n**Projekt:** other\n", None,
     ("hermes-jit", "STATE.md: SSOT w Obsidianie")),
    ("**Projekt:** Boocco\n", None, ("boocco", "STATE.md: Projekt")),
    ("# State\n", {"scope": "scoped"}, ("scoped", ".planning/jit.json")),
    ("# State\n", None, ("plain", "nazwa katalogu")),
])
def test_dossier_name_follows_cockpit_rules(tmp_path, state_md, jit_json, expected):
    root = tmp_path / "plain"
    (root / ".planning").mkdir(parents=True)
    (root / ".planning" / "STATE.md").write_text(state_md, encoding="utf-8")
    if jit_json is not None:
        (root / ".planning" / "jit.json").write_text(json.dumps(jit_json), encoding="utf-8")
    found = project_links.dossier(root)
    assert (found["name"], found["source"]) == expected
    assert found["uri"].startswith("obsidian://open?vault=Wojciech&file=projects%2F")


def test_worktrees_outside_git_is_an_error_not_empty(tmp_path):
    assert "error" in project_links.worktrees(tmp_path)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_render_function_string_tests_in_node():
    # Pin the TAP reporter: newer Node defaults to the "spec" reporter even off a TTY.
    res = subprocess.run(["node", "--test", "--test-reporter=tap", str(NODE_RENDER_TEST)],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-2000:]
    assert "# fail 0" in res.stdout
