#!/bin/bash
cd /home/moatasim/fixed
source /home/moatasim/fixed/venv/bin/activate

while true
do
  echo "[$(date)] Starting Guardian Bot..."
  python /home/moatasim/fixed/run_all_bots.py
  echo "[$(date)] Bot stopped. Restarting in 5s..."
  sleep 5
done
