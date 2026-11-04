"""Fake `claude -p --output-format json` for hub action tests; never calls a model.

Mode from $FAKE_AGENT_MODE: success (default), fail, error_result, garbage, hang. $FAKE_AGENT_SLEEP delays the
answer. Every call writes <pid>.start.json (argv, cwd, stdin, time) and, if it finishes, <pid>.end.json to
$FAKE_AGENT_LOG.
"""

import json
import os
import sys
import time
from pathlib import Path

REPORT_TEXT = "## Podsumowanie\nRaport testowy \U0001F680 z dowodem README.md:1\n"
HANG_SECONDS = 120


def record(log_dir: Path, name: str, payload: dict) -> None:
    (log_dir / f"{os.getpid()}.{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    mode = os.environ.get("FAKE_AGENT_MODE", "success")
    log_dir = Path(os.environ["FAKE_AGENT_LOG"])
    log_dir.mkdir(parents=True, exist_ok=True)
    stdin = sys.stdin.read()
    record(log_dir, "start", {"argv": sys.argv, "cwd": os.getcwd(), "stdin": stdin, "time": time.time()})
    time.sleep(float(os.environ.get("FAKE_AGENT_SLEEP", "0")))
    if mode == "hang":
        time.sleep(HANG_SECONDS)
    record(log_dir, "end", {"time": time.time()})
    if mode == "fail":
        sys.stderr.write("boom: model unavailable\n")
        return 3
    if mode == "garbage":
        print("this is not json")
        return 0
    if mode == "error_result":
        print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True,
                          "total_cost_usd": 0.5, "usage": {"output_tokens": 7}}))
        return 0
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": REPORT_TEXT,
                      "total_cost_usd": 0.0123, "num_turns": 4, "duration_ms": 1500,
                      "usage": {"input_tokens": 100, "output_tokens": 50}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
