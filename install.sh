#!/usr/bin/env bash
# JIT Context one-line installer: sets up every agent host it finds on this machine
# (Claude Code, Hermes, OpenCode, Agent Zero). Safe to re-run; re-running also updates.
#
#   curl -fsSL https://raw.githubusercontent.com/wojciechwiesner/jit-context/master/install.sh | bash
#   ... | bash -s -- --only claude-code,hermes     # pick hosts
#   ... | bash -s -- --dry-run                     # show changes, touch nothing
set -euo pipefail

REPO_URL="${JIT_REPO_URL:-https://github.com/wojciechwiesner/jit-context.git}"
INSTALL_DIR="${JIT_HOME:-$HOME/.jit-context}"
BIN_DIR="$HOME/.local/bin"
MIN_PYTHON="3.11"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

find_python() {
  # Stock macOS ships python3 3.9, so try versioned binaries first.
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    candidate="$(command -v "$candidate" || true)"
    if [[ -n "$candidate" ]] && "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  if command -v uv >/dev/null; then
    uv python install --quiet "$MIN_PYTHON" >&2 && uv python find "$MIN_PYTHON" && return 0
  fi
  return 1
}

ensure_venv() {
  # Hooks are registered against this exact interpreter (sys.executable at
  # install time) - it must have the package's runtime deps importable, or
  # every SessionStart/UserPromptSubmit hook fails with ModuleNotFoundError.
  # Runs inside $(...): a bare `exit` here would only kill the subshell, so
  # failures use `return 1` and the caller checks the exit status instead.
  local venv_dir="$INSTALL_DIR/.venv" venv_python="$INSTALL_DIR/.venv/bin/python3"
  if [[ ! -x "$venv_python" ]]; then
    say "Creating virtualenv at $venv_dir" >&2
    if command -v uv >/dev/null; then
      uv venv --quiet --python "$PYTHON" "$venv_dir" >&2 || { warn "uv venv failed"; return 1; }
    else
      "$PYTHON" -m venv "$venv_dir" >&2 || { warn "python -m venv failed (Debian/Ubuntu: sudo apt install python3-venv, or install uv: https://docs.astral.sh/uv/)"; return 1; }
    fi
  fi
  say "Installing dependencies into virtualenv" >&2
  if command -v uv >/dev/null; then
    uv pip install --quiet --python "$venv_python" -e "$INSTALL_DIR" >&2 || { warn "uv pip install failed"; return 1; }
  else
    "$venv_python" -m pip install --quiet --upgrade -e "$INSTALL_DIR" >&2 || { warn "pip install failed"; return 1; }
  fi
  echo "$venv_python"
}

command -v git >/dev/null || die "git is required"
PYTHON="$(find_python)" || die "python >= $MIN_PYTHON is required (install it, or install uv: https://docs.astral.sh/uv/)"
say "Using $("$PYTHON" -V 2>&1) at $PYTHON"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  say "Updating $INSTALL_DIR"
  # Fast-forward only: local commits or edits are never overwritten.
  git -C "$INSTALL_DIR" pull --ff-only --quiet || warn "could not fast-forward, keeping the local checkout"
else
  say "Cloning into $INSTALL_DIR"
  git clone --depth 1 --quiet "$REPO_URL" "$INSTALL_DIR"
fi

PYTHON="$(ensure_venv)" || die "could not set up the jit-context virtualenv"
say "Hooks and CLI will run under $PYTHON"

say "Linking the jit CLI into $BIN_DIR"
mkdir -p "$BIN_DIR"
WRAPPER_MARK="# jit-context installer wrapper"
if [[ -e "$BIN_DIR/jit" ]] && ! grep -q "$WRAPPER_MARK" "$BIN_DIR/jit"; then
  cp -p "$BIN_DIR/jit" "$BIN_DIR/jit.bak.$(date +%Y%m%d-%H%M%S)"
fi
cat > "$BIN_DIR/jit" <<EOF
#!/usr/bin/env bash
$WRAPPER_MARK
exec "$PYTHON" "$INSTALL_DIR/src/init.py" "\$@"
EOF
chmod +x "$BIN_DIR/jit"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "add $BIN_DIR to your PATH to use 'jit'" ;; esac

say "Setting up agent hosts"
status=0
"$PYTHON" "$INSTALL_DIR/src/init.py" install "$@" || status=$?

if [[ " $* " != *" --dry-run "* ]]; then
  say "Health check"
  if "$PYTHON" "$INSTALL_DIR/src/init.py" doctor >/dev/null 2>&1; then
    echo "  doctor   OK"
  else
    warn "some checks need attention (optional services such as the Observatory): run 'jit doctor'"
  fi
fi

echo
say "Done. Update: re-run the same curl line. Remove: jit uninstall"
echo "    https://github.com/wojciechwiesner/jit-context  (DOI 10.5281/zenodo.22649542)"
exit "$status"
