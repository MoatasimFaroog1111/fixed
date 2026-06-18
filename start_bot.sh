#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
fi

while true
do
  echo "[$(date)] Starting Guardian Bot..."
  python "$SCRIPT_DIR/run_all_bots.py"
  echo "[$(date)] Bot stopped. Restarting in 5s..."
  sleep 5
done
