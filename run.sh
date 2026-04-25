#!/usr/bin/env bash
# Run the voice-todo-agent locally. Uses .env via python-dotenv (loaded in backend).
set -e
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
