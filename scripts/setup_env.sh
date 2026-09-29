#!/usr/bin/env bash
set -euo pipefail
PYTHON_EXE="${1:-python3}"
VENV_DIR="${2:-.venv}"

echo "==> Creating virtual environment in $VENV_DIR"
"$PYTHON_EXE" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
fi
echo "Python environment ready."
