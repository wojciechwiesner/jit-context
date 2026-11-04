"""Security regressions for the real local HTTP handler (no model substitute)."""
import importlib.util
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("cockpit_server", Path(__file__).with_name("server.py"))
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class BridgeSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / ".planning").mkdir()
        (root / ".planning/state.html").write_text("<h1>Private cockpit</h1>")
        self.token = secrets.token_urlsafe(32)
        self.server = SERVER.create_server({"token": self.token, "model": "unused",
                                            "projects": {"/projects/test/": str(root)}}, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, route, method="GET", body=None, headers=None):
        request = urllib.request.Request(self.base + route, body, headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_private_page_loads_but_paths_do_not_escape_registry(self):
        self.assertEqual(self.request("/projects/test/")[0], 200)
        self.assertEqual(self.request("/../../etc/passwd")[0], 404)

    def test_cross_origin_reads_and_posts_are_rejected(self):
        for origin in ("https://evil.example", "null"):
            self.assertEqual(self.request("/projects/test/", headers={"Origin": origin})[0], 403)
        self.assertEqual(self.request("/api/chat", "POST", b"{}", {"Origin": "https://evil.example"})[0], 403)

    def test_chat_requires_token_and_valid_messages(self):
        self.assertEqual(self.request("/api/chat", "POST", b"{}")[0], 401)
        headers = {"X-Cockpit-Token": self.token, "Origin": "null"}
        self.assertEqual(self.request("/api/chat", "POST", b"{}", headers)[0], 400)
        self.assertEqual(self.request("/api/chat", "POST", b"x" * 131073, headers)[0], 413)

    def test_preflight_for_authenticated_file_chat(self):
        self.assertEqual(self.request("/api/chat", "OPTIONS", headers={"Origin": "null"})[0], 204)

    def test_provider_timeout_returns_json_and_releases_lock(self):
        from unittest.mock import patch
        body = json.dumps({"messages": [{"role": "user", "content": "test"}]}).encode()
        headers = {"X-Cockpit-Token": self.token}
        with patch.object(SERVER, "complete", side_effect=TimeoutError("test timeout")):
            status, payload = self.request("/api/chat", "POST", body, headers)
        self.assertEqual(status, 502)
        self.assertIn("TimeoutError", json.loads(payload)["error"])
        self.assertTrue(SERVER.CHAT_LOCK.acquire(blocking=False))
        SERVER.CHAT_LOCK.release()

    def test_dns_rebinding_host_is_rejected(self):
        self.assertEqual(self.request("/health", headers={"Host": "evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
