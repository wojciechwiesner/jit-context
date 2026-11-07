"""Feedby default: key format, idempotent snippet injection, provision flow with a fake remote."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from feedby_std import keys, provision, remote, snippet, store

HTML_PAGE = "<!doctype html>\n<html>\n  <body>\n    <main>hi</main>\n  </body>\n</html>\n"
TSX_ROOT = "export function Shell() {\n  return (\n    <html>\n      <body>\n        {children}\n        <Scripts />\n      </body>\n    </html>\n  )\n}\n"
KEY = "wk_live_" + "A" * 43


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_generated_key_matches_feedby_format_and_hash():
    key = keys.generate_widget_key()
    assert keys.is_valid_key(key) and key.startswith("wk_live_") and len(key) == 8 + 43
    assert keys.hash_widget_key(key) == hashlib.sha256(key.encode()).hexdigest()
    assert keys.mask(key).endswith(key[-4:]) and key not in keys.mask(key)


def test_html_injection_is_idempotent_and_before_body_close():
    once = snippet.inject(HTML_PAGE, "html", KEY)
    twice = snippet.inject(once, "html", KEY)
    assert once == twice
    assert once.count(snippet.MARK_START) == 1
    assert once.index(snippet.SCRIPT_SRC) < once.index("</body>")
    assert snippet.strip(once) == HTML_PAGE


def test_key_rotation_replaces_block_in_place():
    other = "wk_live_" + "B" * 43
    rotated = snippet.inject(snippet.inject(HTML_PAGE, "html", KEY), "html", other)
    assert other in rotated and KEY not in rotated and rotated.count(snippet.MARK_END) == 1


def test_partial_without_body_gets_block_appended():
    out = snippet.inject("<footer>x</footer>", "html", KEY)
    assert out.startswith("<footer>x</footer>\n") and snippet.has_block(out)


def test_astro_scripts_are_inline_and_jsx_goes_before_scripts():
    astro = snippet.inject(HTML_PAGE, "astro", KEY)
    assert "<script is:inline src=" in astro
    tsx = snippet.inject(TSX_ROOT, "jsx", KEY)
    assert tsx.index("feedby:start") < tsx.index("<Scripts />")
    assert "dangerouslySetInnerHTML" in tsx and snippet.inject(tsx, "jsx", KEY) == tsx


def test_jsx_without_anchor_is_refused():
    with pytest.raises(ValueError):
        snippet.inject("export const x = 1\n", "jsx", KEY)


def test_config_lets_page_config_win():
    block = snippet.render("html", KEY, "en")
    config_json = json.dumps({"widgetKey": KEY, "locale": "en"})
    assert f"Object.assign({config_json},window.FeedbyConfig||{{}})" in block


def test_invalid_slug_rejected():
    for bad in ["", "A", "x;drop", "a b", "-lead"]:
        with pytest.raises(ValueError):
            remote.check_slug(bad)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("JIT_HUB_DIR", str(tmp_path / "hub"))
    path = tmp_path / "proj"
    path.mkdir()
    git(path, "init", "-q")
    (path / "index.html").write_text(HTML_PAGE)
    (path / "other.txt").write_text("base\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "init")
    return path


@pytest.fixture
def fake_remote(monkeypatch):
    db = {"projects": {}, "keys": {}}

    def ensure(slug, name, org_id=remote.DEFAULT_ORG_ID):
        created = slug not in db["projects"]
        db["projects"].setdefault(slug, f"pid-{slug}")
        return {"id": db["projects"][slug], "slug": slug, "created": "1" if created else "0"}

    monkeypatch.setattr(remote, "ensure_project", ensure)
    monkeypatch.setattr(remote, "find_project", lambda slug: {"id": db["projects"][slug]} if slug in db["projects"] else None)
    monkeypatch.setattr(remote, "insert_widget_key", lambda pid, h, label: db["keys"].setdefault(h, pid))
    monkeypatch.setattr(remote, "key_is_live", lambda h: next((s for s, p in db["projects"].items() if db["keys"].get(h) == p), None))
    return db


def test_provision_creates_key_commits_only_mounts_and_reuses_key(repo, fake_remote):
    (repo / "other.txt").write_text("dirty, must not be committed\n")
    first = provision.provision(repo, "demo-proj", "Demo", ["index.html"])
    assert first.project_created and not first.key_reused and first.commit
    assert git(repo, "show", "--name-only", "--format=", "HEAD") == "index.html"
    assert "Developed by Wojciech Wiesner" in git(repo, "log", "-1", "--format=%B")
    assert git(repo, "status", "--porcelain") == "M other.txt"
    entry = store.get("demo-proj")
    assert entry["key"] in (repo / "index.html").read_text()
    assert oct(store.store_path().stat().st_mode & 0o777) == "0o600"
    second = provision.provision(repo, "demo-proj", "Demo", ["index.html"])
    assert second.key_reused and not second.mounts_changed and not second.commit
    assert len(fake_remote["keys"]) == 1


def test_dry_run_changes_nothing(repo, fake_remote):
    result = provision.provision(repo, "dry-proj", "Dry", ["index.html"], dry_run=True)
    assert result.dry_run and result.mounts_changed == ["index.html"]
    assert (repo / "index.html").read_text() == HTML_PAGE
    assert not fake_remote["projects"] and store.get("dry-proj") is None


def test_dirty_mount_file_is_refused(repo, fake_remote):
    (repo / "index.html").write_text(HTML_PAGE + "<!-- wip -->\n")
    with pytest.raises(RuntimeError, match="uncommitted"):
        provision.provision(repo, "wip-proj", "Wip", ["index.html"])
    assert not fake_remote["projects"]


def test_probes_send_named_user_agent(monkeypatch):
    """REGRESSION INVARIANT: Cloudflare rejects Python-urllib (error 1010); probes must name themselves."""
    import urllib.request
    from feedby_std import verify
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request.get_header("User-agent"))
        raise urllib.error.URLError("offline")

    import urllib.error
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert verify.probe_key(KEY) == verify.KEY_UNKNOWN
    assert verify.page_serves_widget("https://example.test/", KEY) is None
    assert seen == [verify.USER_AGENT, verify.USER_AGENT]


def test_minified_body_close_never_lands_inside_a_script():
    """REGRESSION INVARIANT: `</script></body>` on one line (Astro minified) must get the block AFTER
    </script>; inserting at line start put it inside the script on theones.io."""
    page = "<html><body><p>x</p>\n\t\t<script>\n\t\t\tinit();\n\t\t</script></body></html>"
    out = snippet.inject(page, "html", KEY)
    before = out[: out.index("<!-- feedby:start")]
    assert before.count("<script") == before.count("</script>")
    assert out.index("feedby:end") < out.index("</body>")
    assert snippet.inject(out, "html", KEY) == out


def test_strip_restores_original_exactly():
    """REGRESSION INVARIANT: strip(inject(x)) == x for indented and minified pages."""
    minified = "<html><body><script>a()</script></body></html>"
    for page in (HTML_PAGE, minified):
        assert snippet.strip(snippet.inject(page, "html", KEY)) == page
