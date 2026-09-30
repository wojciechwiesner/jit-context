#!/usr/bin/env bash
# Component ablation on a fixed GAIA task set. Each arm gets a fresh state dir/DB,
# so no learned priors leak between arms. Same worker, same turn budget for all arms.
# Usage: benchmarks/run_ablation.sh <task_ids_csv_file> <out_dir> [parallel]
set -euo pipefail

IDS_FILE="$1"
OUT="$2"
PAR="${3:-3}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TURNS="${ABL_MAX_TURNS:-25}"
WORKER="${ABL_WORKER:-gemini-3.8-flash}"
IDS="$(tr -d '\n' < "$IDS_FILE")"
mkdir -p "$OUT"

# arm  CAPSULE GUARD CONSCIENCE INTUITION PLANNER JUDGE
ARMS="A_full        1 1 1 1 1 1
B_no_capsule  0 1 1 1 1 1
C_no_guard    1 0 1 1 1 1
D_no_conscience 1 1 0 1 1 1
E_no_intuition 1 1 1 0 1 1
F_no_planner  1 1 1 1 0 1
G_bare        0 0 0 0 0 0"

# Optional subset, e.g. ABL_ARMS="A_full G_bare"
if [ -n "${ABL_ARMS:-}" ]; then
  ARMS="$(echo "$ARMS" | grep -wE "^($(echo "$ABL_ARMS" | tr ' ' '|'))")"
fi

run_arm() {
  local name="$1" cap="$2" grd="$3" con="$4" intu="$5" pln="$6" jdg="$7"
  local s="$OUT/$name"
  mkdir -p "$s"
  local judge_flag=""
  [ "$jdg" = "1" ] && judge_flag="--judge"
  ( cd "$REPO" && JIT_STATE_DIR="$s" JIT_DB_PATH="$s/db.sqlite" \
      GAIA_ABL_CAPSULE="$cap" GAIA_ABL_GUARD="$grd" GAIA_ABL_CONSCIENCE="$con" \
      GAIA_ABL_INTUITION="$intu" GAIA_ABL_PLANNER="$pln" \
      .venv/bin/python benchmarks/run_gaia_full_cognitive_system.py \
        --task_ids "$IDS" --mode COGNITIVE --worker "$WORKER" \
        --max_turns "$TURNS" $judge_flag --output "$s/res.json" > "$s/run.log" 2>&1 \
      && echo "exit=0" >> "$s/run.log" || echo "exit=$?" >> "$s/run.log" )
}
export -f run_arm
export OUT REPO TURNS WORKER IDS

echo "$ARMS" | xargs -P "$PAR" -L 1 bash -c 'run_arm "$@"' _
echo "ALL ARMS DONE -> $OUT"
