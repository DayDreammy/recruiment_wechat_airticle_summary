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
    out = subprocess.run(
        ["pgrep", "-f", "rss_article_fetcher_enhanced.py"],
        capture_output=True, text=True,
    ).stdout.strip()
    if out:
        pid = out.splitlines()[0]
        et = subprocess.run(
            ["ps", "-p", pid, "-o", "etime="],
            capture_output=True, text=True,
        ).stdout.strip()
        if parse_etime(et) > 3:
            problems.append(f"抓取进程 PID {pid} 已运行 {et}（>3h），疑似卡死")

    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT MAX(created_at) FROM wechat_articles").fetchone()
    conn.close()
    if row and row[0]:
        newest = datetime.strptime(row[0][:10], "%Y-%m-%d")
        if datetime.now() - newest > timedelta(hours=26):
            problems.append(f"超过 26 小时没有新文章入库（最新发布 {row[0][:10]}）")
    else:
        problems.append("wechat_articles 表为空，抓取可能从未成功")

    if not problems:
        return 0
    subject = "【招聘抓取】异常告警"
    body = "时间：%s\n\n%s\n\n请检查 logs/rss_fetcher.log 与 logs/build_feed.log。" % (
        datetime.now().strftime("%F %T"), "\n".join(problems))
    send_email(subject, body, RECIPIENT, text_type="plain")
    print(subject)
    print(body)
    return 1


if __name__ == "__main__":
    sys.exit(main())
