#!/usr/bin/env bash
# 容器入口：初始化目录 → 安装 crontab → 首次启动补抓一次 → 前台跑 cron。
set -euo pipefail

mkdir -p /app/logs /app/data /app/pdfs
mkdir -p "$(dirname /app/data/message_monitor.db)"

# 首次启动先跑一次抓取（失败不阻塞，cron 会继续兜底）
/app/scripts/run_fetch.sh >> /app/logs/cron.log 2>&1 || true

crontab /app/docker/crontab
echo "[entrypoint] cron started at $(date '+%F %T %Z')"
exec crond -f -l 8
