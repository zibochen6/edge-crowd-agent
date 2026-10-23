#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
if ! test -x "$UV_BIN"; then UV_BIN="$(command -v uv)"; fi
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.10}"
if ! test -x "$PYTHON_BIN"; then echo '需要 Jetson 系统 Python 3.10；可设置 PYTHON_BIN。'; exit 1; fi
if ! test -x .venv/bin/python; then "$UV_BIN" venv --python "$PYTHON_BIN" --system-site-packages .venv; fi
"$UV_BIN" sync --frozen --inexact --python "$PYTHON_BIN"
.venv/bin/python -c "import sys; assert sys.version_info[:2] == (3,10); import tensorrt; print('Python',sys.version.split()[0], 'TensorRT',tensorrt.__version__)"
