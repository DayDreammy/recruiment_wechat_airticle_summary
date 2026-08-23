#!/usr/bin/env bash
# Daily 08:30 recruitment article summary + publish (Mac mini).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
mkdir -p logs data pdfs

# 防止与上一轮重叠（积压补跑时可能耗时较长）
if pgrep -f 'pdfsummary.py' >/dev/null 2>&1; then
  echo "$(date '+%F %T') summary skipped: previous run still active" >> logs/summary.log
  exit 0
fi

exec .venv/bin/python pdfsummary.py \
  "${PDF_DIR:-pdfs}" "${OUTPUT_DIR:-data}" \
  "${PDFSUMMARY_CONFIG:-config.json}" >> logs/summary.log 2>&1
