#!/usr/bin/env bash
# End-to-end check of the Project Hub against a tmp HOME and a tmp project (no network, no model calls):
# jit init -> jit hub scan -> refresh --once -> commit a STATE.md edit in a worktree -> refresh --once ->
# version changed -> Mission Control server on a free port -> curl /api/hub/projects, /hub/<slug>, /api/hub/version.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-/opt/homebrew/bin/python3.11}"
SRC="$REPO/src"
SLUG="hub-e2e-demo"
SERVER_WAIT_TRIES=50
SERVER_WAIT_STEP=0.2

TMP="$(mktemp -d "${TMPDIR:-/tmp}/jit-hub-e2e.XXXXXX")"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2> /dev/null || true; wait "$SERVER_PID" 2> /dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; [ -f "$TMP/server.log" ] && tail -20 "$TMP/server.log" >&2; exit 1; }
step() { echo "== $*"; }

# Isolate every path the runtime derives from HOME or the environment.
export HOME="$TMP/home"
export HERMES_HOME="$HOME/.hermes"
export PYTHONPATH="$SRC"
export JIT_L2_ENABLED=0
unset JIT_STATE_DIR JIT_DB_PATH JIT_HUB_DIR JIT_COCKPIT_BUILDER JIT_HUB_ALLOWED_ORIGINS JIT_HUB_AGENT_CMD \
  JIT_CLAUDE_PROJECTS_DIR OBSIDIAN_VAULT PROJECTS_VAULT PROJECTS_WORKSPACE WORKSPACE_DIR JIT_DEV_LIVE JIT_SRC
mkdir -p "$HOME/Documents/Wojciech/projects" "$TMP/work"

jit() { "$PY" "$SRC/init.py" "$@"; }
git_t() { git -c user.email=e2e@example.com -c user.name=e2e "$@"; }
hub_version() {
  "$PY" -c 'import json, sys; from hub import overview; print(json.dumps(overview.version(sys.argv[1])))' "$SLUG"
}
json_field() { "$PY" -c 'import json, sys; print(json.loads(sys.argv[1]).get(sys.argv[2]) or "")' "$1" "$2"; }

step "tmp project $TMP/work/$SLUG"
PROJECT="$TMP/work/$SLUG"
mkdir -p "$PROJECT/.planning"
printf '# State\n\n## Tasks\n- [ ] first open task\n- [x] done task\n' > "$PROJECT/.planning/STATE.md"
printf '.planning/state.html\n' > "$PROJECT/.gitignore"
printf '# %s\n\nEnd-to-end fixture.\n' "$SLUG" > "$PROJECT/README.md"
git_t -C "$PROJECT" init -q -b main
git_t -C "$PROJECT" add -A
git_t -C "$PROJECT" commit -q -m "first commit"

step "jit init"
jit init "$PROJECT" > "$TMP/init.log" || { cat "$TMP/init.log"; fail "jit init exited non-zero"; }
grep -q "Hub: $SLUG" "$TMP/init.log" || { cat "$TMP/init.log"; fail "jit init did not register $SLUG"; }

step "jit hub scan"
jit hub scan "$TMP/work" > "$TMP/scan.log" || { cat "$TMP/scan.log"; fail "hub scan exited non-zero"; }
jit hub list --json | grep -q "\"slug\": \"$SLUG\"" || fail "registry has no $SLUG"

step "jit hub refresh --once (first build)"
jit hub refresh --once || fail "first refresh failed"
V1="$(hub_version)"
SIG1="$(json_field "$V1" signature)"
[ -n "$SIG1" ] || fail "no signature after the first build: $V1"
[ -f "$PROJECT/.planning/state.html" ] || fail "untracked cockpit was not written in place"

step "edit STATE.md in a worktree and commit it there"
WORKTREE="$TMP/work/$SLUG-wt"
git_t -C "$PROJECT" worktree add -q -b feat/e2e "$WORKTREE"
printf -- '- [ ] task added in the worktree\n' >> "$WORKTREE/.planning/STATE.md"
git_t -C "$WORKTREE" commit -q -am "worktree: add a task to STATE.md"

step "jit hub refresh --once (second build)"
jit hub refresh --once || fail "second refresh failed"
V2="$(hub_version)"
SIG2="$(json_field "$V2" signature)"
[ -n "$SIG2" ] && [ "$SIG2" != "$SIG1" ] || fail "version did not change: before $V1, after $V2"
echo "version changed: ${SIG1:0:12} -> ${SIG2:0:12}"

step "Mission Control server on a free port"
PORT="$("$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
BASE="http://127.0.0.1:$PORT"
"$PY" -m health.livestream --host 127.0.0.1 --port "$PORT" > "$TMP/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq "$SERVER_WAIT_TRIES"); do
  curl -fsS -o /dev/null "$BASE/api/hub/projects" 2> /dev/null && break
  kill -0 "$SERVER_PID" 2> /dev/null || fail "server exited"
  sleep "$SERVER_WAIT_STEP"
done

step "GET /api/hub/projects"
curl -fsS "$BASE/api/hub/projects" > "$TMP/projects.json" || fail "/api/hub/projects"
grep -q "\"$SLUG\"" "$TMP/projects.json" || fail "/api/hub/projects does not list $SLUG"

step "GET /hub/$SLUG"
curl -fsS "$BASE/hub/$SLUG" > "$TMP/cockpit.html" || fail "/hub/$SLUG"
grep -q 'name="jit-hub-csrf"' "$TMP/cockpit.html" || fail "/hub/$SLUG has no CSRF meta"
grep -q "$SLUG" "$TMP/cockpit.html" || fail "/hub/$SLUG does not mention the project"

step "GET /api/hub/version?slug=$SLUG"
V_HTTP="$(curl -fsS "$BASE/api/hub/version?slug=$SLUG")" || fail "/api/hub/version"
[ "$(json_field "$V_HTTP" signature)" = "$SIG2" ] || fail "HTTP version $V_HTTP differs from the last build $V2"

echo "hub e2e OK"
