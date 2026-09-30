#!/usr/bin/env bash
# Benchmark 10 tasks on SWE-bench Verified using OpenRouter small fast model (Qwen 2.5 7B Instruct)
# Compares bare vs JIT arms.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL="${1:-qwen/qwen-2.5-7b-instruct}"
OUT="${2:-$HERE/runs/openrouter_qwen7b_10}"
TURNS="${3:-25}"

OPENROUTER_API_KEY="$(python3 -c 'import re; t=open("/Users/wojciechwiesner/.hermes/.env").read(); m=re.search(r"^OPENROUTER_API_KEY=[\x22\x27]?(.*?)[\x22\x27]?$", t, re.M); print(m.group(1) if m else "")')"
export OPENROUTER_API_KEY

PY="${SWE_PY:-/var/folders/3v/sj3z8dyn2qg962xfx2kmbp3w0000gn/T/swe_lfm/.venv/bin/python}"
if [ ! -f "$PY" ]; then
  PY="$(which python3)"
fi

DATASET="${SWE_DATASET:-$HERE/verified.parquet}"
IDS_FILE="${SWE_IDS:-$HERE/swe_10_ids.txt}"
IDS="$(cat "$IDS_FILE")"

mkdir -p "$OUT"
WORK="$OUT/work"

echo "============================================================" | tee -a "$OUT/run.log"
echo "SWE-bench Verified 10-task OpenRouter benchmark" | tee -a "$OUT/run.log"
echo "Model: $MODEL" | tee -a "$OUT/run.log"
echo "Tasks: $IDS" | tee -a "$OUT/run.log"
echo "Output: $OUT" | tee -a "$OUT/run.log"
echo "Start: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$OUT/run.log"
echo "============================================================" | tee -a "$OUT/run.log"

for arm in jit bare; do
  echo "=== [ARM: $arm] START $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
  "$PY" "$HERE/agent.py" \
    --dataset "$DATASET" \
    --ids "$IDS" \
    --arm "$arm" \
    --model "$MODEL" \
    --provider "openrouter" \
    --api-key "$OPENROUTER_API_KEY" \
    --out "$OUT" \
    --work "$WORK" \
    --max-turns "$TURNS" 2>&1 | grep -v "przekodowa" | tee -a "$OUT/run.log"
  echo "=== [ARM: $arm] FINISHED $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
done

echo "=== ALL ARMS FINISHED $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
