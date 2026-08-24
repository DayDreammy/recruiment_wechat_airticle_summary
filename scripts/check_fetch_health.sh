#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
mkdir -p logs
exec .venv/bin/python scripts/check_fetch_health.py >> logs/notify.log 2>&1
