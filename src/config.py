"""Configuration for JIT-Context Runtime & Epistemic Memory Engine."""

import os
import re
from pathlib import Path
from typing import Optional

# Base directories with dynamic fallback
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DIR = Path(os.environ.get("JIT_STATE_DIR", HERMES_HOME / "state" / "ona-context"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR = STATE_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("JIT_DB_PATH", STATE_DIR / "session_overlay.db"))
LATEST_CONTEXT_SYMLINK = STATE_DIR / "latest_context.xml"

import re

def get_session_dir(session_id: str, project: Optional[str] = None) -> Path:
    """Return dedicated directory for session state isolation, partitioned by project/session_id."""
    safe_project = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(project or "general")).strip() or "general"
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(session_id or "default"))
    s_dir = SESSIONS_DIR / safe_project / safe_id
    s_dir.mkdir(parents=True, exist_ok=True)
    return s_dir

def get_session_db_path(session_id: str, project: Optional[str] = None) -> Path:
    """Return isolated SQLite DB path for this session."""
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(session_id or "default"))
    return get_session_dir(session_id, project) / f"overlay_{safe_id}.db"

def get_session_capsule_path(session_id: str, project: Optional[str] = None) -> Path:
    """Return physical context XML file path for this session."""
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(session_id or "default"))
    return get_session_dir(session_id, project) / f"ona_context_{safe_id}.xml"

def get_session_meta_path(session_id: str, project: Optional[str] = None) -> Path:
    """Return session metadata JSON file path."""
    safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(session_id or "default"))
    return get_session_dir(session_id, project) / f"session_{safe_id}.json"

def resolve_project_workspace_dir(project_name: str) -> Optional[Path]:
    """Find local workspace directory for a project if it exists."""
    if not project_name or project_name in ("general", "unknown"):
        return None
    # Common workspace variations
    raw = str(project_name).strip()
    norm = re.sub(r'[^a-zA-Z0-9_\-]', '-', raw.lower())
    for cand in [
        WORKSPACE_DIR / raw,
        WORKSPACE_DIR / norm,
        WORKSPACE_DIR / raw.replace("-", "_"),
        WORKSPACE_DIR / raw.replace("_", "-"),
    ]:
        if cand.exists() and cand.is_dir():
            return cand
    return None

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
