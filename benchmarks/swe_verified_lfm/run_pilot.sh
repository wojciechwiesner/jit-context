#!/usr/bin/env bash
# Run bare and jit arms sequentially on the same instance ids (single Ollama host).
# Usage: run_pilot.sh <ids_file> <out_dir> [max_turns]
set -euo pipefail
IDS_FILE="$1"; OUT="$2"; TURNS="${3:-25}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${SWE_PY:-python3}"
DATASET="${SWE_DATASET:?set SWE_DATASET to SWE-bench_Verified parquet}"
IDS="$(cat "$IDS_FILE")"
mkdir -p "$OUT"
WORK="$OUT/work"
for arm in bare jit; do
  echo "=== arm $arm start $(date +%H:%M:%S)" >> "$OUT/run.log"
  "$PY" "$HERE/agent.py" --dataset "$DATASET" --ids "$IDS" --arm "$arm" \
    --out "$OUT" --work "$WORK" --max-turns "$TURNS" 2>&1 | grep -v "przekodowa" >> "$OUT/run.log"
done
echo "=== done $(date +%H:%M:%S)" >> "$OUT/run.log"
