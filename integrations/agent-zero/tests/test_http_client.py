from jev_bridge.http_client import JevHTTPClient, _Breaker


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _failing_urlopen(req, timeout=None):
    raise OSError("down")


def test_breaker_opens_after_three(monkeypatch):
    clk = FakeClock()
    b = _Breaker(now_fn=clk)
    for _ in range(3):
        b.record_failure()
    assert b.can_execute() is False  # OPEN
    clk.t += 31.0
    assert b.can_execute() is True  # HALF-OPEN after 30s


def test_client_returns_none_and_opens(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _failing_urlopen)
    c = JevHTTPClient("http://127.0.0.1:9", timeout_s=0.05)
    assert c.rank([{"key": "k", "value": "v"}], "q") is None
    c.rank([], "q")
    c.rank([], "q")
    assert c.breaker.state == "OPEN"
