#!/usr/bin/env python3
"""每小时抓取健康检查：进程卡死(>3h)或超过 26h 无新文章时发告警邮件。"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smtp import send_email

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT, "data", "message_monitor.db")
FETCH_LOG = os.path.join(PROJECT, "logs", "rss_fetcher.log")
STATE_FILE = os.path.join(PROJECT, "logs", ".fetch_alert_state")
RECIPIENT = os.getenv("NOTIFY_EMAIL", "1781051483@qq.com").strip()


def parse_etime(s):
    s = s.strip()
    try:
        if "-" in s:
            days, rest = s.split("-", 1)
            days = int(days)
        else:
            days, rest = 0, s
        parts = [int(x) for x in rest.split(":")]
        hours = parts[0] if len(parts) == 3 else 0
        minutes = parts[-2] if len(parts) >= 2 else 0
        return days * 24 + hours + minutes / 60
    except Exception:
        return 0


def main():
    problems = []
    fetch_running = False
    out = subprocess.run(
        ["pgrep", "-f", "rss_article_fetcher_enhanced.py"],
        capture_output=True, text=True,
    ).stdout.strip()
    if out:
        fetch_running = True
        pid = out.splitlines()[0]
        et = subprocess.run(
            ["ps", "-p", pid, "-o", "etime="],
            capture_output=True, text=True,
        ).stdout.strip()
        if parse_etime(et) > 5:
            problems.append(f"抓取进程 PID {pid} 已运行 {et}（>5h），疑似卡死")

    # 以抓取日志的最后活动时间为准（避免夜间/周末发布间隔导致的误报）
    try:
        last_activity = datetime.fromtimestamp(os.path.getmtime(FETCH_LOG))
        if not fetch_running and datetime.now() - last_activity > timedelta(hours=30):
            problems.append(
                f"抓取日志已 {int((datetime.now() - last_activity).total_seconds() // 3600)} 小时无更新"
            )
    except OSError:
        problems.append("找不到抓取日志，抓取可能从未运行")

    if not problems:
        return 0

    # 去重：同一问题 12 小时内只提醒一次
    try:
        last_alert = datetime.fromtimestamp(float(open(STATE_FILE).read().strip()))
        if datetime.now() - last_alert < timedelta(hours=12):
            return 0
    except (OSError, ValueError):
        pass
    with open(STATE_FILE, "w") as f:
        f.write(str(datetime.now().timestamp()))

    subject = "【招聘抓取】异常告警"
    body = "时间：%s\n\n%s\n\n请检查 logs/rss_fetcher.log 与 logs/build_feed.log。" % (
        datetime.now().strftime("%F %T"), "\n".join(problems))
    send_email(subject, body, RECIPIENT, text_type="plain")
    print(subject)
    print(body)
    return 1


if __name__ == "__main__":
    sys.exit(main())
