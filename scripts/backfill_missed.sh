#!/usr/bin/env bash
# 一次性补跑 8/17 与 8/19-8/22 漏掉的文章（默认日期窗口=发布日=created_at）。
# 先等当前抓取（8/19-8/23 补抓）结束，再逐天跑汇总并标记已处理。
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
mkdir -p logs data

LOCK_DIR="/tmp/recruiment-backfill.lock"
if mkdir "$LOCK_DIR" 2>/dev/null; then
  trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
else
  echo "$(date '+%F %T') backfill skipped: another backfill still running" >> logs/backfill.log
  exit 0
fi

echo "$(date '+%F %T') backfill start: waiting for running fetch to finish" >> logs/backfill.log
for _ in $(seq 1 360); do
  if ! pgrep -f 'rss_article_fetcher_enhanced.py' >/dev/null 2>&1; then
    break
  fi
  sleep 60
done

# 8/19、8/20 在数据源窗口内已过期（未入库），无可补内容
for d in 2026-08-17 2026-08-21 2026-08-22 2026-08-23; do
  echo "$(date '+%F %T') backfill $d starting" >> logs/backfill.log
  PDFSUMMARY_START_DATE="$d" PDFSUMMARY_END_DATE="$d" \
    .venv/bin/python pdfsummary.py pdfs data config.json >> logs/summary.log 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    sqlite3 data/message_monitor.db \
      "UPDATE wechat_articles SET pandora_processed=1 WHERE pandora_processed=0 AND created_at >= '$d 00:00:00' AND created_at <= '$d 23:59:59';" \
      >> logs/backfill.log 2>&1
    echo "$(date '+%F %T') backfill $d done" >> logs/backfill.log
  else
    echo "$(date '+%F %T') backfill $d FAILED rc=$rc" >> logs/backfill.log
  fi
done

echo "$(date '+%F %T') backfill finished" >> logs/backfill.log
