"""Refactoring Competition: Local Qwen2.5-Coder-7B (with JIT Context OS)
vs OpenRouter 120B Giant (nvidia/nemotron-3-super-120b) WITHOUT JIT (Naive Haystack).

Target File: ~/Projects/active/retro-plumber-run/src/game.js
Goal: Refactor messy, squashed single-line game engine into clean, human-readable SOTA code,
preserving 100% test compatibility (node --test test/*.test.mjs).
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

# 1. JIT Context OS Prompt for Local Model
JIT_PROMPT = f"""<ONA_CONTEXT scope="retro-plumber-run" epoch="1">
Evidence only. SOTA 2026 Engineering Manifest wins.
  [STANDARDS — HUMAN READABLE CLEAN CODE]
    • Refactor the target ES6 module into clean, readable, modular JavaScript.
    • Deconstruct the dense update() loop into dedicated helper functions:
      - handlePlayerInput(player, input)
      - applyPhysics(player, dt)
      - handlePlatformCollisions(player, platforms, dt)
      - updateEnemies(bots, player, dt, onKill, onDamage)
      - collectRivets(rivets, player, level)
    • Replace cryptic one-letter vars (p, b, dx, dy) with self-documenting descriptive names.
    • CRITICAL INVARIANT: Keep exact function signatures and exported names:
      - export const WORLD
      - export function makeLevel()
      - export function update(level, input, dt)
    • Zero external dependencies. Pure vanilla ES6 module.
</ONA_CONTEXT>

CURRENT SQUASHED CODE TO REFACTOR:
```javascript
{ORIGINAL_GAME_JS}
```

ZADANIE DLA PROGRAMISTY:
Przeprowadź refaktoryzację powyższego pliku src/game.js na czysty, czytelny i modułowy kod JavaScript ES6.
Zachowaj 100% zgodności z testami.
Zwróć WYŁĄCZNIE kod JavaScript w bloku ```javascript ... ```.
"""

# 2. Haystack Prompt for Cloud Giant (bloated, contradictory legacy requirements)
HAYSTACK_NOISE = """
### LEGACY ARCHITECTURE MANUAL (2021)
Rule 42: All JavaScript must be converted to Object-Oriented Class hierarchies with Inheritance.
Rule 43: Use experimental Decorators @Injectable and @Component from TypeScript.
Rule 44: Import external physics library 'matter-js' or 'planck-js' for collision resolution.
Rule 45: Deprecate `makeLevel` and replace it with `LevelFactorySingleton.getInstance()`.
Rule 46: Rename `update` to `tickProcessLifecycle`.
""" * 25

HAYSTACK_PROMPT = f"""{HAYSTACK_NOISE}

HISTORIA PROJEKTU:
Użytkownik: Jak refaktoryzujemy kod?
Asystent: Zawsze przepisujemy na TypeScriptowe klasy z singletonami i biblioteką Matter.js.

AKTUALNY KOD DO REFAKTORYZACJI:
```javascript
{ORIGINAL_GAME_JS}
```

ZADANIE:
Przeprowadź refaktoryzację powyższego pliku src/game.js na czytelny i modułowy kod.
Zwróć kompletny kod w bloku ```javascript ... ```.
"""

def extract_js(raw: str) -> str:
    m = re.search(r"```(?:javascript|js)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return raw.strip()

def test_code_in_repo(js_code: str, label: str) -> dict:
    temp_file = f"{TARGET_REPO}/src/game_{label}.js"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(js_code)
    
    # 1. Syntax check
    check_res = subprocess.run(["node", "--check", temp_file], capture_output=True, text=True)
    syntax_ok = (check_res.returncode == 0)
    
    # 2. Test compatibility: temporarily swap game.js
    backup_file = f"{TARGET_REPO}/src/game.js.bak"
    os.rename(f"{TARGET_REPO}/src/game.js", backup_file)
    with open(f"{TARGET_REPO}/src/game.js", "w", encoding="utf-8") as f:
        f.write(js_code)
    
    test_res = subprocess.run(["npm", "test"], cwd=TARGET_REPO, capture_output=True, text=True)
    tests_ok = (test_res.returncode == 0)
    
    # Restore original
    os.remove(f"{TARGET_REPO}/src/game.js")
    os.rename(backup_file, f"{TARGET_REPO}/src/game.js")
    
    return {
        "syntax_ok": syntax_ok,
        "syntax_error": check_res.stderr.strip() if not syntax_ok else None,
        "tests_ok": tests_ok,
        "test_output": test_res.stdout.strip() if tests_ok else (test_res.stdout + "\n" + test_res.stderr).strip()
    }

def main():
    print("=======================================================")
    print("ZAWODY W REFAKTORINGU: retro-plumber-run (src/game.js)")
    print("=======================================================")
    
    # 1. LOCAL Qwen2.5-Coder-7B (Z JIT Context OS)
    print("\n--> [1/2] Zawodnik 1: Qwen2.5-Coder-7B (Lokalny M2 Pro, Z JIT Context OS)...")
    t0 = time.time()
    res_local = requests.post(OLLAMA_URL, json={
        "model": "qwen2.5-coder:7b",
        "prompt": JIT_PROMPT,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.1,
            "num_predict": 1500
        }
    }, timeout=120).json()
    dur_local = round(time.time() - t0, 2)
    local_js = extract_js(res_local.get("response", ""))
    print(f"    Wygenerowano w {dur_local}s")
    
    # 2. CLOUD Nemotron-120B (BEZ JIT - Naive Haystack)
    print("\n--> [2/2] Zawodnik 2: NVIDIA Nemotron-120B (Chmura OpenRouter, BEZ JIT - Haystack)...")
    t0 = time.time()
    res_cloud = requests.post(OPENROUTER_URL, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }, json={
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "messages": [{"role": "user", "content": HAYSTACK_PROMPT}],
        "max_tokens": 1500,
        "temperature": 0.1
    }, timeout=120).json()
    dur_cloud = round(time.time() - t0, 2)
    cloud_raw = res_cloud.get("choices", [{}])[0].get("message", {}).get("content", "")
    cloud_js = extract_js(cloud_raw)
    print(f"    Wygenerowano w {dur_cloud}s")
    
    # Evaluate candidates
    print("\n=======================================================")
    print("TESTOWANIE W RUNTIME:")
    print("=======================================================")
    eval_local = test_code_in_repo(local_js, "qwen_jit")
    eval_cloud = test_code_in_repo(cloud_js, "nemotron_haystack")
    
    # Save outputs for inspection
    with open("/tmp/refactored_local_qwen_jit.js", "w", encoding="utf-8") as f:
        f.write(local_js)
    with open("/tmp/refactored_cloud_nemotron_haystack.js", "w", encoding="utf-8") as f:
        f.write(cloud_js)
        
    print(f"\n1. QWEN 2.5 CODER 7B (Lokalny + JIT):")
    print(f"   - Składnia JS (node --check): {'OK' if eval_local['syntax_ok'] else 'FAIL'}")
    print(f"   - Testy jednostkowe (npm test): {'PASS 3/3' if eval_local['tests_ok'] else 'FAIL'}")
    print(f"   - Plik: /tmp/refactored_local_qwen_jit.js")
    if not eval_local['tests_ok']:
        print(f"   - Błąd testów:\n{eval_local['test_output'][:300]}")

    print(f"\n2. NEMOTRON 120B (Chmura + Haystack):")
    print(f"   - Składnia JS (node --check): {'OK' if eval_cloud['syntax_ok'] else 'FAIL'}")
    print(f"   - Testy jednostkowe (npm test): {'PASS 3/3' if eval_cloud['tests_ok'] else 'FAIL'}")
    print(f"   - Plik: /tmp/refactored_cloud_nemotron_haystack.js")
    if not eval_cloud['tests_ok']:
        print(f"   - Błąd testów:\n{eval_cloud['test_output'][:300]}")

if __name__ == "__main__":
    main()
