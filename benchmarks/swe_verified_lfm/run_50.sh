#!/usr/bin/env bash
# Run 50 tasks benchmark on SWE-bench Verified with LFM2.5
# Supports running bare, jit, or both sequentially on local Ollama or remote Ollama.
# Usage: ./run_50.sh [both|jit|bare] [out_dir] [max_turns] [ollama_url]
set -euo pipefail

ARM_TARGET="${1:-both}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${2:-$HERE/runs/run_50}"
TURNS="${3:-25}"
OLLAMA_URL="${4:-${OLLAMA_API:-http://127.0.0.1:11434/api/chat}}"

PY="${SWE_PY:-/var/folders/3v/sj3z8dyn2qg962xfx2kmbp3w0000gn/T/swe_lfm/.venv/bin/python}"
if [ ! -f "$PY" ]; then
  PY="$(which python3)"
fi

DATASET="${SWE_DATASET:-$HERE/verified.parquet}"
IDS_FILE="${SWE_IDS:-$HERE/swe_50_ids.txt}"
IDS="$(cat "$IDS_FILE")"

mkdir -p "$OUT"
WORK="$OUT/work"

if [ "$ARM_TARGET" = "both" ]; then
  ARMS=("jit" "bare")
else
  ARMS=("$ARM_TARGET")
fi

echo "============================================================" | tee -a "$OUT/run.log"
echo "Starting SWE-bench Verified 50-task benchmark" | tee -a "$OUT/run.log"
echo "Arms: ${ARMS[*]}" | tee -a "$OUT/run.log"
echo "Ollama API: $OLLAMA_URL" | tee -a "$OUT/run.log"
echo "Output: $OUT" | tee -a "$OUT/run.log"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$OUT/run.log"
echo "============================================================" | tee -a "$OUT/run.log"

for arm in "${ARMS[@]}"; do
  echo "=== [ARM: $arm] START $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
  "$PY" "$HERE/agent.py" \
    --dataset "$DATASET" \
    --ids "$IDS" \
    --arm "$arm" \
    --ollama "$OLLAMA_URL" \
    --out "$OUT" \
    --work "$WORK" \
    --max-turns "$TURNS" 2>&1 | grep -v "przekodowa" | tee -a "$OUT/run.log"
  echo "=== [ARM: $arm] FINISHED $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
done

echo "=== ALL ARMS FINISHED $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$OUT/run.log"
