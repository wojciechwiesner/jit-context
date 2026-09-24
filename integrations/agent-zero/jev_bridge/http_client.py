"""Optional HTTP backend for Jev. OFF unless jev_http_url set.
Breaker: 3 failures -> OPEN 30s -> HALF-OPEN. None == use local fallback.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Dict, List, Optional


class _Breaker:
    def __init__(self, threshold: int = 3, recovery: float = 30.0, now_fn=time.time):
        self.threshold = threshold
        self.recovery = recovery
        self.now = now_fn
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure = 0.0

    def can_execute(self) -> bool:
        if self.state == "OPEN":
            if self.now() - self.last_failure > self.recovery:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = self.now()
        if self.failures >= self.threshold:
            self.state = "OPEN"


class JevHTTPClient:
    def __init__(self, base_url: str, timeout_s: float = 0.1):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.breaker = _Breaker()

    def rank(self, facts: List[Dict[str, str]], query: str) -> Optional[List[Dict[str, str]]]:
        if not self.base_url or not self.breaker.can_execute():
            return None
        try:
            payload = json.dumps({"query": query, "facts": facts}).encode()
            req = urllib.request.Request(
                self.base_url + "/rank", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                out = json.loads(resp.read())
            order = out.get("order") or []
            self.breaker.record_success()
            return [facts[i] for i in order if isinstance(i, int) and 0 <= i < len(facts)]
        except Exception:
            self.breaker.record_failure()
            return None
