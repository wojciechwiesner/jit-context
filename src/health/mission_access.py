"""Access guard for the livestream / Mission Control server.

The server listens on the Tailscale interface so borg nginx can proxy it as
https://live.borg.tools behind Borg SSO. Rules:
  - loopback callers (this Mac) are always allowed;
  - the trusted proxy (borg, over Tailscale) is allowed only when nginx forwarded an
    SSO identity header, so a bare Tailscale request cannot skip the login;
  - everyone else (LAN, other tailnet nodes) gets 403.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
IDENTITY_HEADERS = ("X-Forwarded-Email", "X-Auth-Request-Email", "X-Forwarded-User")


class HeaderLookup(Protocol):
    """Anything with .get(name) -> str | None (dict, http.client.HTTPMessage)."""

    def get(self, name: str, default=None): ...


def trusted_proxies() -> set[str]:
    raw = os.environ.get("JIT_MC_TRUSTED_PROXIES", "100.118.47.46")
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


@dataclass(frozen=True)
class Access:
    allowed: bool
    user: str | None
    via: str | None  # "local", "sso" or None when denied


def check_access(client_ip: str, headers: HeaderLookup) -> Access:
    if client_ip in LOOPBACK:
        return Access(True, None, "local")
    if client_ip in trusted_proxies():
        for name in IDENTITY_HEADERS:
            value = (headers.get(name) or "").strip()
            if value:
                return Access(True, value, "sso")
    return Access(False, None, None)
