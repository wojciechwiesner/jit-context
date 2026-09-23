"""Configuration for JIT-Context Runtime & Epistemic Memory Engine."""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict, Tuple

# Base directories with dynamic fallback
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DIR = Path(os.environ.get("JIT_STATE_DIR", HERMES_HOME / "state" / "ona-context"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
MODE_FILE = STATE_DIR / "mode.json"
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
L2_DEADLINE_MS = 2000.0

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

# Context Compaction Settings (0.4 input context window threshold, ~400k tokens for Gemini)
CONTEXT_COMPACTION_THRESHOLD_RATIO = float(os.environ.get("JIT_COMPACTION_THRESHOLD", "0.4"))
GEMINI_CONTEXT_WINDOW_TOKENS = int(os.environ.get("JIT_CONTEXT_WINDOW", "1000000"))
COMPACTION_TRIGGER_TOKENS = int(GEMINI_CONTEXT_WINDOW_TOKENS * CONTEXT_COMPACTION_THRESHOLD_RATIO)  # 400,000 tokens

# ---------------------------------------------------------------------------
# Dynamic JIT Configuration Registry
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "active",
    "worker": "routed",
    "tier": "standard",
    "compaction_threshold": 0.4,
    "context_window": 1000000,
    "health_host": "127.0.0.1",
    "health_port": 8765,
    "l0_max_latency_ms": 3.0,
    "l1_max_latency_ms": 10.0,
    "l2_deadline_ms": 2000.0,
    "cb_consecutive_failures_threshold": 3,
    "scope_confidence_threshold": 0.85,
    "telemetry": True,
}

CONFIG_DESCRIPTIONS: Dict[str, str] = {
    "mode": "Runtime mode: active, shadow, passive, or off",
    "worker": "Default Ego Worker: routed, qwen, lfm, or gemini-3.8-flash",
    "tier": "Default profiling depth: simple, standard, deep, xhigh",
    "compaction_threshold": "Context compaction trigger ratio (e.g. 0.4 = 40% of window)",
    "context_window": "Context window capacity in tokens (default: 1,000,000)",
    "health_host": "Local Observatory daemon bind host",
    "health_port": "Local Observatory daemon port",
    "l0_max_latency_ms": "L0 Hot-Path WAL latency budget (ms)",
    "l1_max_latency_ms": "L1 Scope Hysteresis latency budget (ms)",
    "l2_deadline_ms": "L2 Remote Broker fail-open timeout deadline (ms)",
    "cb_consecutive_failures_threshold": "Circuit breaker trips after N failures",
    "scope_confidence_threshold": "Threshold for project scope transition hysteresis",
    "telemetry": "Enable or disable live stream and dashboard telemetry",
}

def load_config() -> Dict[str, Any]:
    """Load merged configuration from mode.json and runtime defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if MODE_FILE.exists():
        try:
            stored = json.loads(MODE_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass
    return cfg

def save_config(cfg: Dict[str, Any]) -> None:
    """Persist configuration to mode.json and mirror to live telemetry state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg["updated_at"] = datetime.now().isoformat()
    MODE_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    live_file = Path("/tmp/hermes-jit-live.json")
    try:
        live_data = json.loads(live_file.read_text(encoding="utf-8")) if live_file.exists() else {}
        live_data.update(cfg)
        live_file.write_text(json.dumps(live_data, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_config_val(key: str, default: Any = None) -> Any:
    """Retrieve a single configuration value."""
    cfg = load_config()
    return cfg.get(key, default)

def set_config_val(key: str, value: Any) -> Tuple[Any, Any]:
    """Set and persist a configuration value with type coercion."""
    cfg = load_config()
    old_val = cfg.get(key)
    # Type coercion
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on") and key != "mode":
            val = True
        elif lowered in ("false", "no", "off") and key != "mode":
            val = False
        else:
            try:
                val = int(value)
            except ValueError:
                try:
                    val = float(value)
                except ValueError:
                    val = value
    else:
        val = value
    cfg[key] = val
    save_config(cfg)
    return old_val, val
