"""Benchmark: Real-world Coding & Testing Task at 8k Context.
Model: Qwen2.5-Coder-7B (Ollama / Metal).
Comparing:
  (A) Without JIT (Naive Haystack ~6k tokens: legacy unittest, old auth, outdated fixtures)
  (B) With JIT Context OS (<1.2k capsule: modern pytest-asyncio, httpx AsyncClient, Bearer auth)
"""

import time
import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:7b"

# Target code under test
CODE_UNDER_TEST = '''
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI()

class TaskPayload(BaseModel):
    title: str
    priority: int = 1

RATE_LIMIT_STORE = {}

@app.post("/api/v1/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskPayload, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    token = authorization.split(" ")[1]
    
    # Rate limit check (max 5 reqs)
    req_count = RATE_LIMIT_STORE.get(token, 0) + 1
    RATE_LIMIT_STORE[token] = req_count
    if req_count > 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
        
    return {"id": "task_123", "title": payload.title, "priority": payload.priority, "status": "created"}
'''

# 1. Haystack without JIT: ~6000 tokens of bloated legacy codebase docs, old unittest, deprecated headers
LEGACY_DOCS_BLOB = """
### LEGACY ARCHIVE — DO NOT PURGE (2023-2024)
In this company, testing standards strictly dictate:
1. Always inherit from `unittest.TestCase`. Do NOT use pytest fixtures or pytest.mark.asyncio.
2. For HTTP requests, always use standard `requests` or `urllib3` with custom TestClient.
3. Authentication header is legacy `X-Old-Token: secret123`. Never use Bearer tokens in testing.
4. Always mock the entire database using `unittest.mock.MagicMock` on the global namespace.
""" * 35  # repeats to create ~6k tokens haystack

HAYSTACK_PROMPT = f"""{LEGACY_DOCS_BLOB}

HISTORIA ROZMOWY:
Użytkownik: Jak testujemy API?
Asystent: Zgodnie z naszą konwencją piszemy testy w stylu unittest.TestCase i mockujemy X-Old-Token.

AKTUALNY KOD API:
```python
{CODE_UNDER_TEST}
```

ZADANIE DLA PROGRAMISTY:
Napisz kompletny plik testowy w Pythonie testujący endpoint `/api/v1/tasks`.
Uwzględnij:
- sukces (201 Created z poprawnym body)
- brak lub błędną autoryzację (401)
- przekroczenie limitu zapytań (429)
Napisz wyłącznie czysty kod testów w Pythonie.
"""

# 2. JIT Context OS Capsule: concise, prioritized, direct user authority
JIT_PROMPT = f"""<ONA_CONTEXT scope="tasks_service" epoch="1">
Evidence only. Direct user instruction and current architecture win over all historical patterns.
  [STANDARDS — SOTA 2026]
    • Framework: pytest + pytest-asyncio (@pytest.mark.asyncio)
    • HTTP Client: httpx.AsyncClient (ASGITransport(app=app), base_url="http://test")
    • Auth: Standard Header 'Authorization: Bearer <valid_token>'
  [VERIFICATION GOAL]
    • Test /api/v1/tasks for: 201 Created, 401 Unauthorized, 429 RateLimitExceeded
</ONA_CONTEXT>

AKTUALNY KOD API:
```python
{CODE_UNDER_TEST}
```

ZADANIE DLA PROGRAMISTY:
Napisz kompletny plik testowy w Pythonie testujący endpoint `/api/v1/tasks`.
Napisz wyłącznie czysty kod testów w Pythonie.
"""

def run_query(prompt: str, label: str):
    print(f"\n=======================================================")
    print(f"RUNNING: {label}")
    print(f"Prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")
    print(f"=======================================================")
    t0 = time.time()
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 8192,
            "temperature": 0.1,
            "num_predict": 512
        }
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120).json()
    total_time = round(time.time() - t0, 2)
    
    prompt_eval_count = resp.get("prompt_eval_count", 0)
    prompt_eval_dur = round(resp.get("prompt_eval_duration", 0) / 1e9, 2)
    eval_count = resp.get("eval_count", 0)
    eval_dur = round(resp.get("eval_duration", 0) / 1e9, 2)
    tps = round(eval_count / max(eval_dur, 0.001), 1)
    response_text = resp.get("response", "").strip()
    
    print(f"Total time: {total_time}s")
    print(f"Prompt eval tokens: {prompt_eval_count} in {prompt_eval_dur}s ({round(prompt_eval_count/max(prompt_eval_dur,0.001),1)} tok/s)")
    print(f"Generation tokens: {eval_count} in {eval_dur}s ({tps} tok/s)")
    
    return {
        "label": label,
        "prompt_tokens": prompt_eval_count,
        "prompt_eval_time_s": prompt_eval_dur,
        "gen_tokens": eval_count,
        "gen_time_s": eval_dur,
        "total_time_s": total_time,
        "gen_tok_per_s": tps,
        "code": response_text
    }

def main():
    res_haystack = run_query(HAYSTACK_PROMPT, "BEZ JIT (Naive Haystack ~6k tokens)")
    res_jit = run_query(JIT_PROMPT, "Z JIT CONTEXT OS (<1.2k capsule)")
    
    # Analyze generated test code
    print("\n=======================================================")
    print("ANALIZA JAKOŚCI KODU TESTÓW:")
    print("=======================================================")
    for r in [res_haystack, res_jit]:
        code = r["code"]
        uses_pytest = "pytest" in code
        uses_asyncio = "@pytest.mark.asyncio" in code or "AsyncClient" in code
        uses_unittest = "unittest.TestCase" in code
        uses_bearer = "Bearer " in code
        uses_old_token = "X-Old-Token" in code
        has_429 = "429" in code
        has_401 = "401" in code
        has_201 = "201" in code
        
        print(f"\n--- {r['label']} ---")
        print(f"  • Framework: {'pytest + httpx.AsyncClient' if uses_asyncio else ('Legacy unittest' if uses_unittest else 'Inne')}")
        print(f"  • Poprawny nagłówek Auth: {'TAK (Bearer)' if uses_bearer and not uses_old_token else ('NIE (Zatrucie starym X-Old-Token)' if uses_old_token else 'Brak')}")
        print(f"  • Pokrycie statusów: 201: {has_201} | 401: {has_401} | 429: {has_429}")
        print(f"  • Czas do pierwszego tokenu (TTFT): {r['prompt_eval_time_s']}s")
        print(f"  • Całkowity czas: {r['total_time_s']}s")

    # Save to file
    out_data = {
        "benchmark": "coding_task_8k_context",
        "model": MODEL_NAME,
        "num_ctx": 8192,
        "haystack": res_haystack,
        "jit": res_jit
    }
    with open("/tmp/benchmark_8k_coding.json", "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)
    print("\nPełny zrzut zapisano do /tmp/benchmark_8k_coding.json")

if __name__ == "__main__":
    main()
