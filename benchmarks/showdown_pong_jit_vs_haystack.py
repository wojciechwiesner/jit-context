"""Showdown: Local Qwen2.5-Coder-7B with JIT Context OS
vs OpenRouter 120B Giant (nvidia/nemotron-3-super-120b) WITHOUT JIT (Naive Haystack).

Task: Code a playable, visual, standalone Pong HTML5 game.
"""

import os
import re
import time
import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_KEY = os.popen("grep OPENROUTER_API_KEY ~/.zshrc | cut -d= -f2").read().strip()
CLOUD_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
LOCAL_MODEL = "qwen2.5-coder:7b"

# JIT Capsule for Local Model
JIT_PROMPT = """<ONA_CONTEXT scope="games" epoch="1">
Evidence only. Direct user instruction wins.
  [STANDARDS — SOTA 2026 PLAYABLE WEB GAME]
    • Deliverable: Single standalone HTML file with CSS and JavaScript included (<!DOCTYPE html>).
    • Visuals: Dark neon theme (#0f172a background, vibrant cyan #06b6d4 player paddle, hot pink #f43f5e AI paddle, glowing ball).
    • Gameplay: Player (left) controlled by Mouse movement or Up/Down arrows vs Smart AI (right).
    • Physics: Ball velocity angles change based on where it strikes the paddle; speed increases slightly on rally.
    • UI: Live score HUD (Player vs Computer), neon score display, restart button on game over.
    • Quality: Zero external dependencies, runs instantly on load in any modern browser.
</ONA_CONTEXT>

ZADANIE DLA PROGRAMISTY:
Napisz kompletną, gotową do gry i efektowną wizualnie grę w Pong w jednym pliku HTML (z <style> i <script>).
Wygeneruj WYŁĄCZNIE kompletny kod HTML zaczynający się od <!DOCTYPE html>.
"""

# Bloated Haystack for Cloud Giant (contradictory legacy instructions, deprecated ASCII, lost-in-the-middle)
LEGACY_TRASH = """
### RETRO CONSOLE SPECIFICATION (1982 ARCHIVE)
Rule 1: Always use 2-player keyboard mode only. Keys A and Z for Player 1, Keys K and M for Player 2.
Rule 2: Never use HTML5 canvas or high refresh rate. Use plain table cells or monospace ASCII text blocks.
Rule 3: Colors are strictly banned. Everything must be monochrome grey (#888888) and black.
Rule 4: Do not include artificial intelligence or computer opponent.
Rule 5: Frame rate must be limited to 10 FPS using setTimeout(100).
""" * 30

HAYSTACK_PROMPT = f"""{LEGACY_TRASH}

HISTORIA ARCHIWALNA:
Użytkownik: Jak pisać gry retro?
Asystent: Zgodnie z naszą konwencją piszemy tylko tryb dwuosobowy na klawiaturze A/Z, bez AI, w szarościach.

AKTUALNE ZAPYTANIE UŻYTKOWNIKA:
Napisz kompletną, gotową do gry i efektowną wizualnie grę w Pong w jednym pliku HTML (z <style> i <script>).
Wygeneruj kompletny kod HTML.
"""

def extract_html(raw_text: str) -> str:
    # Try finding html block
    m = re.search(r"```html\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"(<!DOCTYPE html.*?>.*?</html>)", raw_text, re.DOTALL | re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return raw_text.strip()

def run_local_jit():
    print(f"--> Odpytywanie LOCAL: {LOCAL_MODEL} (Z JIT Context OS)...")
    t0 = time.time()
    res = requests.post(OLLAMA_URL, json={
        "model": LOCAL_MODEL,
        "prompt": JIT_PROMPT,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.2,
            "num_predict": 1400
        }
    }, timeout=120).json()
    dur = round(time.time() - t0, 2)
    text = res.get("response", "")
    html = extract_html(text)
    eval_count = res.get("eval_count", len(text.split()))
    tps = round(eval_count / max(dur, 0.001), 1)
    print(f"    Local ukończono w {dur}s ({eval_count} tokenów, {tps} tok/s)")
    return html, dur, tps

def run_cloud_haystack():
    print(f"--> Odpytywanie CLOUD GIANT: {CLOUD_MODEL} (BEZ JIT - Naive Haystack ~6k tok)...")
    t0 = time.time()
    res = requests.post(OPENROUTER_URL, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }, json={
        "model": CLOUD_MODEL,
        "messages": [{"role": "user", "content": HAYSTACK_PROMPT}],
        "max_tokens": 1400,
        "temperature": 0.2
    }, timeout=120).json()
    dur = round(time.time() - t0, 2)
    choices = res.get("choices", [])
    if choices:
        raw = choices[0].get("message", {}).get("content", "")
    else:
        raw = f"Error: {res.get('error')}"
    html = extract_html(raw)
    print(f"    Cloud ukończono w {dur}s")
    return html, dur, raw

def main():
    local_html, dur_local, tps_local = run_local_jit()
    cloud_html, dur_cloud, raw_cloud = run_cloud_haystack()

    path_local = "/tmp/pong_local_qwen_jit.html"
    path_cloud = "/tmp/pong_openrouter_haystack.html"

    with open(path_local, "w", encoding="utf-8") as f:
        f.write(local_html)

    with open(path_cloud, "w", encoding="utf-8") as f:
        f.write(cloud_html)

    print("\n=======================================================")
    print("PODSUMOWANIE SHOWDOWN:")
    print("=======================================================")
    print(f"1. LOCAL Qwen2.5-Coder-7B (Z JIT):")
    print(f"   - Plik: {path_local}")
    print(f"   - Czas: {dur_local}s ({tps_local} tok/s)")
    print(f"   - Posiada HTML/Canvas: {'<!DOCTYPE' in local_html or '<canvas' in local_html}")
    print(f"   - Posiada AI paletkę: {'ai' in local_html.lower() or 'computer' in local_html.lower()}")
    print(f"   - Posiada obsługę myszy/strzałek: {'mousemove' in local_html.lower() or 'arrow' in local_html.lower()}")
    print(f"   - Kolory neon / dark: {'#0f172a' in local_html or 'cyan' in local_html.lower() or '#06b6d4' in local_html}")

    print(f"\n2. CLOUD Nemotron-120B (BEZ JIT - Haystack):")
    print(f"   - Plik: {path_cloud}")
    print(f"   - Czas: {dur_cloud}s")
    print(f"   - Posiada HTML/Canvas: {'<!DOCTYPE' in cloud_html or '<canvas' in cloud_html}")
    print(f"   - Skażenie archiwalną szarością/A/Z: {'#888888' in cloud_html or 'keya' in cloud_html.lower() or 'keyz' in cloud_html.lower()}")
    print(f"   - Dwuosobowy keyboard bez AI: {'player 2' in cloud_html.lower() or 'keys' in cloud_html.lower()}")

if __name__ == "__main__":
    main()
