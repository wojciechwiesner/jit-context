"""Configuration for JIT-Context Runtime & Epistemic Memory Engine."""

import os
from pathlib import Path

# Base directories with dynamic fallback
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DIR = Path(os.environ.get("JIT_STATE_DIR", HERMES_HOME / "state" / "ona-context"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("JIT_DB_PATH", STATE_DIR / "session_overlay.db"))

# Dynamic vault and workspace resolution
def _resolve_default_vault() -> Path:
    env_vault = os.environ.get("OBSIDIAN_VAULT") or os.environ.get("PROJECTS_VAULT")
    if env_vault:
        return Path(env_vault)
    # Check common vault locations
    for cand in [Path.home() / "Documents" / "Wojciech", Path.home() / "Documents" / "Vault", Path.home() / "Documents" / "projects"]:
        if cand.exists():
            return cand
    return Path.home() / "Documents" / "projects"

def _resolve_default_workspace() -> Path:
    env_ws = os.environ.get("PROJECTS_WORKSPACE") or os.environ.get("WORKSPACE_DIR")
    if env_ws:
        return Path(env_ws)
    for cand in [Path.home() / "Projects" / "active", Path.home() / "Projects", Path.home() / "workspace"]:
        if cand.exists():
            return cand
    return Path.cwd()

VAULT_DIR = _resolve_default_vault()
PROJECTS_DIR = VAULT_DIR / "projects" if (VAULT_DIR / "projects").exists() else VAULT_DIR
WORKSPACE_DIR = _resolve_default_workspace()

# Performance & Timeouts
L0_MAX_LATENCY_MS = 3.0
L1_MAX_LATENCY_MS = 10.0
L2_DEADLINE_MS = 600.0

# Circuit Breaker settings
CB_CONSECUTIVE_FAILURES_THRESHOLD = 3
CB_COOLDOWN_SECONDS = 30.0

# Scope Hysteresis settings
SCOPE_SUSTAINED_TURNS = 2
SCOPE_CONFIDENCE_THRESHOLD = 0.85

# Remote Broker / Gateway (optional)
BORG_GATEWAY_URL = os.environ.get("BORG_GATEWAY_URL", "http://100.118.47.46:8000")
BORG_GATEWAY_KEY = os.environ.get("BORG_GATEWAY_KEY", "")

# Local Health Server
HEALTH_SERVER_HOST = os.environ.get("JIT_HEALTH_HOST", "127.0.0.1")
HEALTH_SERVER_PORT = int(os.environ.get("JIT_HEALTH_PORT", "8765"))
