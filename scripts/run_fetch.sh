#!/usr/bin/env bash
# Hourly RSS fetch for recruitment article summary (Mac mini).
# Data source: local wechat2rss aggregate feed (scripts/build_recruitment_feed.py).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
mkdir -p logs pdfs data

# wechat2rss RSS token 未在 .env 配置时，直接从本机容器环境读取
if [ -z "${WECHAT2RSS_RSS_TOKEN:-}" ]; then
  WECHAT2RSS_RSS_TOKEN=$(docker inspect wechat2rss \
    --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | sed -n 's/^RSS_TOKEN=//p')
  export WECHAT2RSS_RSS_TOKEN
fi

# 防止与上一轮重叠（首轮补抓可能要数小时）
if pgrep -f 'rss_article_fetcher_enhanced.py' >/dev/null 2>&1; then
  echo "$(date '+%F %T') fetch skipped: previous run still active" >> logs/rss_fetcher.log
  exit 0
fi

# 1. 从本机 wechat2rss 聚合生成 feed
.venv/bin/python scripts/build_recruitment_feed.py >> logs/build_feed.log 2>&1
if [ $? -ne 0 ]; then
  echo "$(date '+%F %T') feed build failed, skip fetch" >> logs/rss_fetcher.log
  exit 1
fi

# 2. 抓取并生成 PDF
FEED_PATH="$(pwd)/data/recruitment_feed.xml"
if [ "${FETCH_SKIP_PDF:-0}" = "1" ]; then
  exec .venv/bin/python rss_article_fetcher_enhanced.py \
    --rss-url "file://${FEED_PATH}" \
    --db-path "${WECHAT_SQLITE_DB_PATH:-data/message_monitor.db}" \
    --pdf-dir pdfs --skip-pdf >> logs/rss_fetcher.log 2>&1
fi
exec .venv/bin/python rss_article_fetcher_enhanced.py \
  --rss-url "file://${FEED_PATH}" \
  --db-path "${WECHAT_SQLITE_DB_PATH:-data/message_monitor.db}" \
  --pdf-dir pdfs >> logs/rss_fetcher.log 2>&1
