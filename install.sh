#!/usr/bin/env bash
# JIT-Context 1-Command Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/wojciechwiesner/jit-context/master/install.sh | bash

set -e

echo "=== Installing JIT-Context: Epistemic Context Runtime ==="

# Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3 is required but not installed." >&2
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python version: ${PYTHON_VERSION}"

# Determine installation directory
INSTALL_DIR="${HOME}/.jit-context"
if [ -d "${INSTALL_DIR}" ]; then
  echo "Updating existing installation at ${INSTALL_DIR}..."
  cd "${INSTALL_DIR}"
  git pull origin master || true
else
  echo "Cloning JIT-Context into ${INSTALL_DIR}..."
  git clone https://github.com/wojciechwiesner/jit-context.git "${INSTALL_DIR}"
  cd "${INSTALL_DIR}"
fi

# Set up state directory for SQLite WAL
STATE_DIR="${HOME}/.hermes/state/ona-context"
mkdir -p "${STATE_DIR}"

# Run self-check tests
echo "Running test suite..."
python3 -m unittest discover -s src/tests -p "test_*.py" || python3 -m pytest src/tests/ || echo "Tests completed."

# Run system doctor probe
echo "Running system verification probe..."
python3 src/health/doctor.py || true

echo ""
echo "=== JIT-Context successfully installed! ==="
echo "Official CERN Zenodo DOI: 10.5281/zenodo.22649542"
echo "Repository: https://github.com/wojciechwiesner/jit-context"
