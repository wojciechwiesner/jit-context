"""Configuration for Hermes JIT Context OS & Borg Context Broker plugin (ona-context)."""

import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DIR = HERMES_HOME / "state" / "ona-context"
STATE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = STATE_DIR / "session_overlay.db"
PROJECTS_DIR = Path(os.environ.get("PROJECTS_VAULT", Path.home() / "Documents" / "projects"))

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

# Remote Broker / Gateway
BORG_GATEWAY_URL = os.environ.get("BORG_GATEWAY_URL", "http://100.118.47.46:8000")
BORG_GATEWAY_KEY = os.environ.get("BORG_GATEWAY_KEY", "")

# Local Health Server
HEALTH_SERVER_HOST = "127.0.0.1"
HEALTH_SERVER_PORT = 8765
