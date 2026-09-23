#!/usr/bin/env python3
"""
Honest SWE Benchmark: 5 Tasks WITHOUT JIT (Raw Baseline).
No <ONA_CONTEXT> capsule, no AST pre-extraction, no pre-calculated line snippets.
Prompt delivers standard task description + full raw file contents.
Verification: Physical pytest execution.
"""

import os
import sys
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ENV_PATH = Path.home() / ".hermes" / ".env"
GOOGLE_API_KEY = None
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("GOOGLE_API_KEY="):
            GOOGLE_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

if not GOOGLE_API_KEY:
    print("ERROR: GOOGLE_API_KEY not found in ~/.hermes/.env", file=sys.stderr)
    sys.exit(1)

TASKS_BASE = Path("/tmp/honest_swe_raw_5")
if TASKS_BASE.exists():
    shutil.rmtree(TASKS_BASE)
TASKS_BASE.mkdir(parents=True)

# Import same tasks
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_honest_swe_5 import TASKS

print("==================================================================")
print(" 🔬 HONEST SWE BENCHMARK: RAW BASELINE (WITHOUT JIT)")
print("==================================================================")

results = []

for idx, task in enumerate(TASKS, 1):
    tid = task["id"]
    tdir = TASKS_BASE / tid
    tdir.mkdir(parents=True, exist_ok=True)

    src_file = tdir / task["file"]
    test_file = tdir / f"test_{task['file']}"

    src_file.write_text(task["code"])
    test_file.write_text(task["test"])

    # Baseline verification
    base_res = subprocess.run(["pytest", str(test_file)], capture_output=True, text=True)
    if base_res.returncode == 0:
        continue

    # RAW PROMPT (NO JIT, NO AST WORKING SET, NO CAPSULE)
    # Just raw instructions + full raw file text
    prompt = f"""You are a software engineer fixing a bug in {task['file']}.

File contents of {task['file']}:
```python
{task['code']}
```

Issue to fix:
{task['title']}
{task['description']}

Generate a surgical patch. Return ONLY valid JSON:
{{"tool": "patch", "old_string": "exact unique text to replace", "new_string": "replacement text"}}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json"
        }
    }

    t0 = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            latency = round(time.time() - t0, 2)
            usage = data.get("usageMetadata", {})
            patch_data = json.loads(text)
    except Exception as e:
        print(f"[{idx}/5] {tid} -> API/JSON ERROR: {e}")
        results.append({"id": tid, "status": "ERROR", "error": str(e)})
        continue

    # Apply patch
    old_str = patch_data.get("old_string", "")
    new_str = patch_data.get("new_string", "")
    current_content = src_file.read_text()

    if old_str not in current_content:
        print(f"[{idx}/5] {tid} -> ❌ PATCH MATCH FAIL: old_string not found in file ({latency}s)")
        results.append({
            "id": tid,
            "status": "FAIL_PATCH_MISMATCH",
            "latency_s": latency,
            "tokens": usage.get("totalTokenCount", 0)
        })
        continue

    src_file.write_text(current_content.replace(old_str, new_str, 1))

    # Post-patch pytest
    post_res = subprocess.run(["pytest", str(test_file)], capture_output=True, text=True)
    if post_res.returncode == 0:
        print(f"[{idx}/5] {tid} -> ✅ VERIFIED PASS ({latency}s | {usage.get('totalTokenCount', 0)} tok)")
        results.append({
            "id": tid,
            "status": "VERIFIED_PASS",
            "exit_code": 0,
            "latency_s": latency,
            "tokens": usage.get("totalTokenCount", 0)
        })
    else:
        print(f"[{idx}/5] {tid} -> ❌ PYTEST FAILED ({latency}s | exit code: {post_res.returncode})")
        results.append({
            "id": tid,
            "status": "FAIL_TEST_REJECTED",
            "exit_code": post_res.returncode,
            "latency_s": latency,
            "tokens": usage.get("totalTokenCount", 0)
        })

passed = sum(1 for r in results if r["status"] == "VERIFIED_PASS")
print("\n==================================================================")
print(f" RAW BASELINE RESULTS: {passed} / {len(TASKS)} PASSED ({passed/len(TASKS)*100:.1f}%)")
print("==================================================================")

out_file = Path("/tmp/honest_swe_raw_5_results.json")
out_file.write_text(json.dumps(results, indent=2))
