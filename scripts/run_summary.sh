#!/usr/bin/env bash
# Daily 08:30 recruitment article summary + publish (Mac mini).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
mkdir -p logs data pdfs

# 防止与上一轮重叠：目录锁 + 6 小时陈旧锁接管（避免任意 pdfsummary 进程导致误跳过）
LOCK_DIR="/tmp/recruiment-summary.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [ -d "$LOCK_DIR" ] && find "$LOCK_DIR" -mmin +360 -print 2>/dev/null | grep -q .; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
    mkdir "$LOCK_DIR" 2>/dev/null || {
      echo "$(date '+%F %T') summary skipped: lock busy" >> logs/summary.log
      exit 0
    }
  else
    echo "$(date '+%F %T') summary skipped: previous run still active" >> logs/summary.log
    exit 0
  fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

exec .venv/bin/python pdfsummary.py \
  "${PDF_DIR:-pdfs}" "${OUTPUT_DIR:-data}" \
  "${PDFSUMMARY_CONFIG:-config.json}" >> logs/summary.log 2>&1
