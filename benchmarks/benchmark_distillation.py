"""Full benchmark comparing:
1. Qwen 3.5 9B MTP (Local Ollama Metal)
2. Qwen 2.5 Coder 7B (Local Ollama Metal)
3. Liquid LFM-2.5 2.6B (OpenRouter)
4. Gemini Flash via your direct GOOGLE_API_KEY (from ~/.hermes/.env)

Testing distillation quality, speed, latency and reduction ratio.
"""

import os
import re
import json
import time
import requests

def get_google_key():
    lines = open(os.path.expanduser("~/.hermes/.env")).readlines()
    return [l.split("=", 1)[1].strip() for l in lines if l.startswith("GOOGLE_API_KEY")][0]

def get_openrouter_key():
    return os.popen("grep OPENROUTER_API_KEY ~/.zshrc | cut -d= -f2").read().strip()

RAW_UNPRUNED_INPUT = """
[CURRENT — direct user]
• [IMPORTANT: Background process proc_4ba097e814f9 completed normally (exit code 0).
Command: ollama pull hf.co/unsloth/Qwen3.5-9B-MTP-GGUF:Q4_K_M
Output:
███████████▏ 5.9 GB                         
pulling f40af5231eaf: 100% ▕██████████████████▏  182 B                         
pulling 5a40d1f77168: 100% ▕██████████████████▏ 918 MB                         
pulling 6669e2993fff: 100% ▕██████████████████▏   71 B                         
pulling 6e6ac006b587: 100% ▕██████████████████▏  627 B                         
verifying sha256 digest ⠴ pulling manifest 
pulling e8dd94817e95: 100% ▕██████████████████▏ 5.9 GB                         
pulling f40af5231eaf: 100% ▕██████████████████▏  182 B                         
pulling 5a40d1f77168: 100% ▕██████████████████▏ 918 MB                         
pulling 6669e2993fff: 100% ▕██████████████████▏   71 B                         
pulling 6e6ac006b587: 100% ▕██████████████████▏  627 B                         
verifying sha256 digest 
writing manifest 
success]
• Review the conversation above and update the skill library. Be ACTIVE — most sessions produce at least one skill update, even if small. A pass that does nothing is a missed learning opportunity, not a neutral outcome.
Protected skills: Bundled skills, Hub-installed skills, Skills in skills.external_dirs.
• USER REAL GOAL: zrefaktoryzuj plik src/game.js w projekcie retro-plumber-run, aby rozbic update na male funkcje z zachowaniem export const WORLD, export function makeLevel i export function update(level, input, dt). Testy musza przejsc: npm test.

[STALE PROJECT CACHE - aipraca]
Ostatnia aktualizacja: 2026-09-07
Status ogolny: Wdrozone na produkcje (workex.borg.tools, zabezpieczony Borg SSO) — 42 w 100% fizycznie zweryfikowane i potwierdzone aplikacje z twardymi dowodami (w tym 30 oficjalnych maili w skrzynce himalaya od m.in. Scalo, Spyrosoft, CodiLime, dmTECH, Mindbox, Leocode, cyber_Folks, Braver IT, Scurri, Arche Solutions, Addepto oraz 12 bezposrednich stron thankyou/success w systemach ATS Traffit/NoFluffJobs).
Odpowiedzialny: Wojciech Wiesner (wojciech@theones.io)
Domena: https://workex.borg.tools/ (Zabezpieczona przez Borg SSO: Dex + OAuth2-Proxy)
Host: borgtools (100.118.47.46, ssh borg-ts)

[INVARIANTS TO PRESERVE]
- Invariant I1: Direct user message wins over history.
- Invariant I4: Anti-self-poisoning (assistant weight 0.0).
- Invariant I8: Capsule size < 1.5k tokens.
"""

DISTILLATION_SYSTEM_PROMPT = """You are the Context Distiller for Hermes JIT Context OS.
Your ONLY job is to distill noisy input into a pristine, minimal, structured <ONA_CONTEXT> capsule.

Strict Rules:
1. Strip all terminal progress bars, ASCII noise, and background download hashes. Replace with a 1-line note if completed.
2. Filter out stale/unrelated project contexts (e.g. if the task is retro-plumber-run, do not copy 50 lines of aipraca ATS emails).
3. Extract ONLY the active project, current user goal/instruction, and necessary invariants.
4. Output MUST be strictly valid XML matching:
<ONA_CONTEXT scope="..." confidence="0.00-1.00">
  <CURRENT>...</CURRENT>
  <PROJECT>...</PROJECT>
  <CONSTRAINTS>...</CONSTRAINTS>
</ONA_CONTEXT>
5. DO NOT output thinking or reasoning outside the XML. Final output must be concise (< 1,500 chars)."""

def test_local_ollama(model_name, label):
    print(f"\n---> Testing {label} ({model_name})...")
    t0 = time.time()
    payload = {
        "model": model_name,
        "prompt": f"{DISTILLATION_SYSTEM_PROMPT}\n\nRAW INPUT TO DISTILL:\n{RAW_UNPRUNED_INPUT}",
        "stream": False,
        "options": {
            "num_ctx": 4096,
            "temperature": 0.1,
            "num_predict": 1024
        }
    }
    try:
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=90).json()
        dur = round(time.time() - t0, 2)
        raw_res = r.get("response", "")
        eval_count = r.get("eval_count", 0)
        eval_dur = round(r.get("eval_duration", 0) / 1e9, 2)
        tps = round(eval_count / max(eval_dur, 0.001), 1)
        return {
            "name": label,
            "duration": dur,
            "eval_count": eval_count,
            "tps": tps,
            "response": raw_res
        }
    except Exception as e:
        return {"name": label, "error": str(e), "duration": round(time.time() - t0, 2)}

def test_liquid_openrouter():
    label = "Liquid LFM-2.5 2.6B (Cloud)"
    print(f"\n---> Testing {label}...")
    key = get_openrouter_key()
    t0 = time.time()
    payload = {
        "model": "liquid/lfm-2.5-2.6b:free",
        "messages": [
            {"role": "system", "content": DISTILLATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"RAW INPUT TO DISTILL:\n{RAW_UNPRUNED_INPUT}"}
        ],
        "temperature": 0.1,
        "max_tokens": 1024
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json=payload, timeout=60).json()
        dur = round(time.time() - t0, 2)
        choice = r.get("choices", [{}])[0]
        msg = choice.get("message", {}).get("content", "")
        usage = r.get("usage", {})
        completion_tokens = usage.get("completion_tokens", 0)
        tps = round(completion_tokens / max(dur, 0.001), 1)
        return {
            "name": label,
            "duration": dur,
            "eval_count": completion_tokens,
            "tps": tps,
            "response": msg
        }
    except Exception as e:
        return {"name": label, "error": str(e), "duration": round(time.time() - t0, 2)}

def test_gemini_direct():
    label = "Google Gemini Flash (Direct GOOGLE_API_KEY)"
    print(f"\n---> Testing {label}...")
    key = get_google_key()
    t0 = time.time()
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={key}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{DISTILLATION_SYSTEM_PROMPT}\n\nRAW INPUT TO DISTILL:\n{RAW_UNPRUNED_INPUT}"}]}
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024
        }
    }
    try:
        r = requests.post(url, json=payload, timeout=30).json()
        dur = round(time.time() - t0, 2)
        part = r.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        usage = r.get("usageMetadata", {})
        out_toks = usage.get("candidatesTokenCount", 0)
        tps = round(out_toks / max(dur, 0.001), 1)
        return {
            "name": label,
            "duration": dur,
            "eval_count": out_toks,
            "tps": tps,
            "response": part
        }
    except Exception as e:
        return {"name": label, "error": str(e), "duration": round(time.time() - t0, 2)}

def evaluate_quality(res_text):
    clean = re.sub(r"<think>.*?</think>", "", res_text, flags=re.DOTALL).strip()
    clean = clean.replace("```xml", "").replace("```", "").strip()
    
    stripped_bars = "████" not in clean and "pulling manifest" not in clean
    stripped_ats = "thankyou/success" not in clean and "Scalo" not in clean
    kept_task = "game.js" in clean and "retro-plumber-run" in clean and "update" in clean
    kept_invariants = "I1" in clean or "I4" in clean or "I8" in clean or "Invariant" in clean
    valid_xml = "<ONA_CONTEXT" in clean and "</ONA_CONTEXT>" in clean
    
    char_len = len(clean)
    score = sum([stripped_bars, stripped_ats, kept_task, kept_invariants, valid_xml])
    
    return {
        "char_len": char_len,
        "stripped_progress_bars": stripped_bars,
        "stripped_stale_ats": stripped_ats,
        "kept_user_task": kept_task,
        "kept_invariants": kept_invariants,
        "valid_xml": valid_xml,
        "score_out_of_5": score,
        "clean_sample": clean[:400] + ("..." if len(clean) > 400 else "")
    }

def main():
    print("="*80)
    print("BENCHMARK DESTYLACJI I REDUKCJI KONTEKSTU — DIRECT API KEYS")
    print(f"Rozmiar surowego wejścia: {len(RAW_UNPRUNED_INPUT)} znaków")
    print("="*80)
    
    runners = [
        ("qwen3.5-9b-mtp", "Qwen 3.5 9B MTP (Lokalny)", lambda: test_local_ollama("qwen3.5-9b-mtp", "Qwen 3.5 9B MTP")),
        ("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B (Lokalny)", lambda: test_local_ollama("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B")),
        ("lfm-2.5", "Liquid LFM-2.5 2.6B (Cloud)", test_liquid_openrouter),
        ("gemini-flash", "Gemini Flash (Direct Key)", test_gemini_direct),
    ]
    
    results = []
    for model_id, label, runner in runners:
        res = runner()
        if "error" in res:
            print(f"BŁĄD {label}: {res['error']}")
            results.append({"label": label, "error": res["error"], "duration": res["duration"]})
        else:
            eval_q = evaluate_quality(res["response"])
            print(f"--> {label}: {eval_q['score_out_of_5']}/5 | Czas: {res['duration']}s | Znaków: {eval_q['char_len']} | Tok/s: {res.get('tps', 0)}")
            results.append({
                "label": label,
                "duration": res["duration"],
                "tps": res.get("tps", 0),
                "eval": eval_q,
                "raw": res["response"]
            })
            
    print("\n" + "="*85)
    print(f"{'Model':<30} | {'Czas [s]':<8} | {'Tok/s':<6} | {'Jakość':<7} | {'Długość [zn]':<12} | {'Redukcja':<9}")
    print("="*85)
    for r in results:
        if "error" in r:
            print(f"{r['label']:<30} | {r['duration']:<8.2f} | {'ERR':<6} | {'0/5':<7} | {'-':<12} | {'-':<9}")
        else:
            q = r["eval"]
            red = round((1 - q["char_len"] / len(RAW_UNPRUNED_INPUT)) * 100, 1)
            print(f"{r['label']:<30} | {r['duration']:<8.2f} | {r['tps']:<6.1f} | {q['score_out_of_5']}/5    | {q['char_len']:<12} | -{red}%")
            
    with open("/tmp/distillation_benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nPełne wyniki zapisane do: /tmp/distillation_benchmark_results.json")

if __name__ == "__main__":
    main()
