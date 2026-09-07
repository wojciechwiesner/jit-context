"""Clean, 100% symmetrical refactoring duel.
Both models receive the EXACT SAME prompt, zero artificial noise.
Target: ~/Projects/active/retro-plumber-run/src/game.js
"""

import os
import re
import time
import json
import subprocess
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.popen("grep OPENROUTER_API_KEY ~/.zshrc | cut -d= -f2").read().strip()

TARGET_REPO = "/Users/wojciechwiesner/Projects/active/retro-plumber-run"
ORIGINAL_GAME_JS = open(f"{TARGET_REPO}/src/game.js", "r", encoding="utf-8").read()

CLEAN_PROMPT = f"""Refactor this JavaScript (ES6) module to be clean, human-readable, and modular.
Rules:
1. Deconstruct the dense update() loop into clear, focused helper functions with descriptive variable names.
2. Maintain 100% backward compatibility with all exports:
   - export const WORLD
   - export function makeLevel()
   - export function update(level, input, dt)
3. Zero external dependencies. Pure vanilla ES6.
4. Return ONLY the refactored code inside ```javascript ... ```.

Source code:
```javascript
{ORIGINAL_GAME_JS}
```
"""

def extract_js(raw: str) -> str:
    m = re.search(r"```(?:javascript|js)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return raw.strip()

def run_tests_on_code(js_code: str) -> dict:
    backup_file = f"{TARGET_REPO}/src/game.js.bak"
    os.rename(f"{TARGET_REPO}/src/game.js", backup_file)
    with open(f"{TARGET_REPO}/src/game.js", "w", encoding="utf-8") as f:
        f.write(js_code)
    
    check_res = subprocess.run(["node", "--check", f"{TARGET_REPO}/src/game.js"], capture_output=True, text=True)
    syntax_ok = (check_res.returncode == 0)
    
    test_res = subprocess.run(["npm", "test"], cwd=TARGET_REPO, capture_output=True, text=True)
    tests_ok = (test_res.returncode == 0)
    
    # Restore original
    os.remove(f"{TARGET_REPO}/src/game.js")
    os.rename(backup_file, f"{TARGET_REPO}/src/game.js")
    
    return {
        "syntax_ok": syntax_ok,
        "tests_ok": tests_ok,
        "syntax_error": check_res.stderr.strip() if not syntax_ok else "",
        "test_output": test_res.stdout.strip() if tests_ok else (test_res.stdout + "\n" + test_res.stderr).strip()
    }

def main():
    print("==================================================================")
    print("CZYSTY POJEDYNEK 1:1 (IDENTYCZNY PROMPT, ZERO SZUMU)")
    print("==================================================================")
    
    # Model 1: Local Qwen2.5-Coder-7B
    print("\n--> [1/2] LOCAL: Qwen2.5-Coder-7B (Apple M2 Pro Metal)...")
    t0 = time.time()
    res_local = requests.post(OLLAMA_URL, json={
        "model": "qwen2.5-coder:7b",
        "prompt": CLEAN_PROMPT,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.1,
            "num_predict": 1500
        }
    }, timeout=120).json()
    dur_local = round(time.time() - t0, 2)
    local_js = extract_js(res_local.get("response", ""))
    tokens_local = res_local.get("eval_count", 0)
    tps_local = round(tokens_local / max(dur_local, 0.001), 1)
    print(f"    Czas: {dur_local}s | Tokeny: {tokens_local} ({tps_local} tok/s)")
    
    # Model 2: OpenRouter Cloud Model
    print("\n--> [2/2] CLOUD: NVIDIA Nemotron-3.5-Lightning (OpenRouter)...")
    t0 = time.time()
    res_cloud = requests.post(OPENROUTER_URL, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }, json={
        "model": "nvidia/nemotron-3.5-lightning:free",
        "messages": [{"role": "user", "content": CLEAN_PROMPT}],
        "max_tokens": 1500,
        "temperature": 0.1
    }, timeout=120).json()
    dur_cloud = round(time.time() - t0, 2)
    choices = res_cloud.get("choices", [{}])
    raw_cloud = choices[0].get("message", {}).get("content", "")
    cloud_js = extract_js(raw_cloud)
    tokens_cloud = res_cloud.get("usage", {}).get("completion_tokens", 0)
    print(f"    Czas: {dur_cloud}s | Tokeny: {tokens_cloud}")
    
    # Save outputs
    file_local = "/tmp/clean_duel_qwen7b.js"
    file_cloud = "/tmp/clean_duel_cloud.js"
    with open(file_local, "w") as f: f.write(local_js)
    with open(file_cloud, "w") as f: f.write(cloud_js)
    
    # Run tests on both
    print("\n==================================================================")
    print("WERYFIKACJA W RUNTIME (npm test):")
    print("==================================================================")
    ev_local = run_tests_on_code(local_js)
    ev_cloud = run_tests_on_code(cloud_js)
    
    print(f"\n1. QWEN 2.5 CODER 7B (Lokalny M2 Pro):")
    print(f"   - Czas generacji: {dur_local}s ({tps_local} tok/s)")
    print(f"   - Składnia (node --check): {'OK' if ev_local['syntax_ok'] else 'BŁĄD'}")
    print(f"   - Testy (npm test): {'PASS 3/3' if ev_local['tests_ok'] else 'FAIL'}")
    print(f"   - Zapisano do: {file_local}")
    if not ev_local['tests_ok']:
        print(f"   - Logi błędu:\n{ev_local['test_output'][:300]}")
        
    print(f"\n2. NEMOTRON-3.5-LIGHTNING (Chmura OpenRouter):")
    print(f"   - Czas generacji: {dur_cloud}s")
    print(f"   - Składnia (node --check): {'OK' if ev_cloud['syntax_ok'] else 'BŁĄD'}")
    print(f"   - Testy (npm test): {'PASS 3/3' if ev_cloud['tests_ok'] else 'FAIL'}")
    print(f"   - Zapisano do: {file_cloud}")
    if not ev_cloud['tests_ok']:
        print(f"   - Logi błędu:\n{ev_cloud['test_output'][:300]}")

    # Metrics comparison
    print("\n==================================================================")
    print("STATYSTYKI KODU:")
    print("==================================================================")
    print(f"Oryginalny game.js: {len(ORIGINAL_GAME_JS.splitlines())} linii, {len(ORIGINAL_GAME_JS)} znaków")
    print(f"Qwen 7B (lokalny):   {len(local_js.splitlines())} linii, {len(local_js)} znaków")
    print(f"Nemotron (chmura):   {len(cloud_js.splitlines())} linii, {len(cloud_js)} znaków")

if __name__ == "__main__":
    main()
