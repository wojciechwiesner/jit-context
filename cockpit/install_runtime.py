#!/usr/bin/env python3
"""Install a private loopback cockpit service for an explicitly selected project."""
import argparse
import json
import os
import plistlib
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PORT = 8778
LABEL = "io.theones.project-cockpit"
HOME = Path.home()
STATE = HOME / ".hermes/state/project-cockpit"
CONFIG = STATE / "runtime.json"
PLIST = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    root = args.project.resolve()
    if not (root / ".planning/STATE.md").is_file():
        raise SystemExit("Project STATE.md is missing")
    ignored = subprocess.run(["git", "check-ignore", ".planning/state.html"], cwd=root,
                             capture_output=True).returncode == 0
    if (root / "state.html").exists():
        ignored = ignored and subprocess.run(["git", "check-ignore", "state.html"], cwd=root,
                                            capture_output=True).returncode == 0
    if not ignored:
        raise SystemExit("Refusing to embed private runtime data into non-ignored HTML")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise SystemExit(f"Port {PORT} is occupied; deployment stopped")
    STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    backup = HOME / "backups/project-cockpit" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=True)
    for file in (CONFIG, PLIST):
        if file.exists():
            shutil.copy2(file, backup / file.name)
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {
        "url": f"http://127.0.0.1:{PORT}", "token": secrets.token_urlsafe(32),
        "model": "gemini-3.8-flash", "projects": {}}
    config["model"] = "gemini-3.8-flash"
    route = f"/projects/{args.slug}/"
    config["projects"][route] = str(root)
    CONFIG.write_text(json.dumps(config, indent=2))
    os.chmod(CONFIG, 0o600)
    service = STATE / "service"
    service.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__).with_name("server.py"), service / "server.py")
    log = STATE / "service.log"
    definition = {"Label": LABEL, "ProgramArguments": [sys.executable,
        str(service / "server.py"), "--config", str(CONFIG), "--port", str(PORT)],
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 15,
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
        "WorkingDirectory": str(service)}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(definition))
    os.chmod(PLIST, 0o600)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True)
    print(f"Local cockpit installed: {config['url']}{route}; backup: {backup}")


if __name__ == "__main__":
    main()
