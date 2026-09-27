#!/usr/bin/env bash
# One-command local start (macOS or Linux). Demo mode: no key, no network after install.
# Keeps existing data in ./data (run history is preserved across restarts).
#   ./scripts/start.sh            -> http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required (3.12 recommended)"'
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
./.venv/bin/pip install -q -r requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null || { echo "npm not found: install Node.js 20+ (e.g. brew install node@20)"; exit 1; }
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi
export LLM_PROVIDER="${LLM_PROVIDER:-demo}"
echo "Starting on http://127.0.0.1:8000 (provider: $LLM_PROVIDER, data: ./data). Ctrl+C to stop."
exec ./.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "${PORT:-8000}"
