#!/usr/bin/env python3
"""Run the slice judge and rewrite a preview after every test."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "results" / "wynajmujemy_slice" / "live.html"


class Preview:
    def __init__(self, out: Path):
        self.out = out
        self.rows = []
        self.seen = set()

    def pytest_runtest_logreport(self, report):
        if report.when == "teardown":
            return
        if report.when == "setup" and not report.failed:
            return
        if report.nodeid in self.seen and report.when != "call":
            return
        self.seen.add(report.nodeid)
        message = ""
        if report.failed:
            message = report.longreprtext.splitlines()[-1][:240] if report.longreprtext else "failed"
        self.rows.append({
            "name": report.nodeid.split("::")[-1],
            "outcome": report.outcome,
            "seconds": round(report.duration, 3),
            "message": message,
        })
        self.write()

    def write(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        passed = sum(1 for row in self.rows if row["outcome"] == "passed")
        failed = sum(1 for row in self.rows if row["outcome"] == "failed")
        body = "\n".join(self._row(row) for row in self.rows)
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="2">
<title>Wynajmujemy slice</title>
<style>
body {{ margin: 0; background: #0d0e12; color: #e8e6e3; font: 15px/1.45 ui-sans-serif, sans-serif; }}
main {{ max-width: 920px; margin: 0 auto; padding: 28px 20px 48px; }}
h1 {{ font-size: 22px; font-weight: 560; margin: 0 0 8px; }}
p {{ color: #a8a29e; margin: 0 0 18px; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ border-top: 1px solid #2a2c33; padding: 10px 8px; vertical-align: top; }}
.ok {{ color: #8fbc8f; }}
.bad {{ color: #e07a5f; }}
.msg {{ color: #a8a29e; font-family: ui-monospace, monospace; font-size: 12px; }}
</style>
</head>
<body>
<main>
<h1>Wynajmujemy slice</h1>
<p>{passed} passed, {failed} failed, {len(self.rows)} finished. This page reloads itself.</p>
<table>{body}</table>
</main>
</body>
</html>
"""
        self.out.write_text(page, encoding="utf-8")
        self.out.with_suffix(".json").write_text(json.dumps({
            "passed": passed,
            "failed": failed,
            "rows": self.rows,
        }, indent=2), encoding="utf-8")

    @staticmethod
    def _row(row: dict) -> str:
        kind = "ok" if row["outcome"] == "passed" else "bad"
        return (
            "<tr>"
            f"<td class=\"{kind}\">{html.escape(row['outcome'])}</td>"
            f"<td>{html.escape(row['name'])}</td>"
            f"<td>{row['seconds']}s</td>"
            f"<td class=\"msg\">{html.escape(row['message'])}</td>"
            "</tr>"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solution", default=str(ROOT / "starter"))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    solution = Path(args.solution).resolve()
    os.environ["WYNAJMUJEMY_SOLUTION"] = str(solution)
    out = Path(args.out)
    plugin = Preview(out)
    code = pytest.main([
        str(ROOT / "tests" / "test_slice.py"),
        "-q",
        "--tb=line",
    ], plugins=[plugin])
    print(f"preview {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
