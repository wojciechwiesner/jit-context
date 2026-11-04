#!/usr/bin/env bash
# Independent gate for the Project Hub loop: tests, syntax, size and emoji checks on files added on this branch.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1
PY="${PY:-/opt/homebrew/bin/python3.11}"
BASE="${HUB_GATE_BASE:-master}"
fail=0

echo "== pytest"
if ! "$PY" -m pytest src/tests -q -p no:cacheprovider > .loop-runs/gate-pytest.log 2>&1; then
  tail -30 .loop-runs/gate-pytest.log; fail=1
else
  tail -1 .loop-runs/gate-pytest.log
fi

if [ -d cockpit ]; then
  echo "== node --test cockpit/"
  if ! node --test cockpit/ > .loop-runs/gate-node.log 2>&1; then
    grep -E "^not ok|# (pass|fail)" .loop-runs/gate-node.log | head -20; fail=1
  else
    grep -E "^# (pass|fail)" .loop-runs/gate-node.log
  fi
fi

echo "== ruff syntax"
if command -v ruff > /dev/null && ! ruff check --select E9,F63,F7,F82 src --output-format concise; then fail=1; fi

added="$(git diff --name-only --diff-filter=A "$BASE"...HEAD -- src cockpit scripts | grep -E '\.(py|js|html|css|sh)$' | grep -v '/vendor/' | grep -v '^cockpit/.*\.min\.js$' || true)"
echo "== size limit (files added on this branch)"
for f in $added; do
  [ -f "$f" ] || continue
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 300 ]; then echo "too long: $f ($lines lines, max 300)"; fail=1; fi
done

echo "== no emoji in UI and report files"
ui="$(printf '%s\n' $added | grep -E '\.(js|html|css)$|^src/hub/actions/.*\.md$' || true)"
if [ -n "$ui" ]; then
  if ! "$PY" - $ui <<'EOF'
import re, sys
pattern = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]")
bad = [f"{p}:{n}" for p in sys.argv[1:] for n, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1)
       if pattern.search(line)]
print("\n".join(bad[:20]))
sys.exit(1 if bad else 0)
EOF
  then echo "emoji found"; fail=1; fi
fi

echo "== clean tree"
dirty="$(git status --porcelain | grep -v ' .planning/orchestration/QUEUE.md$' || true)"
if [ -n "$dirty" ]; then echo "$dirty" | head -20; fail=1; fi

exit $fail
