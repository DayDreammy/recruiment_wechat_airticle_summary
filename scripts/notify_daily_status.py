#!/usr/bin/env python3
"""每日检查招聘汇总运行状态（launchd 10:00 / Docker cron 10:30）。
成功/失败/无数据都会发邮件到 NOTIFY_EMAIL（默认 1781051483@qq.com）。
"""

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smtp import send_email

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT, "data", "message_monitor.db")
LOG = os.path.join(PROJECT, "logs", "summary.log")
RECIPIENT = os.getenv("NOTIFY_EMAIL", "1781051483@qq.com").strip()


def read_tail(path, limit=400000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tail = read_tail(LOG)

    conn = sqlite3.connect(DB)
    arts = conn.execute(
        "SELECT COUNT(*) FROM wechat_articles "
        "WHERE created_at >= ? AND created_at <= ?",
        (yesterday + " 00:00:00", yesterday + " 23:59:59"),
    ).fetchone()[0]
    proc = conn.execute(
        "SELECT COUNT(*) FROM processed_articles WHERE date(processed_time) = ?",
        (today,),
    ).fetchone()[0]
    conn.close()

    errors = [
        p for p in [
            "插入记录失败", "上传失败", "发送邮件失败",
            "Traceback (most recent call last)", "CRITICAL",
        ]
        if p in tail
    ]
    feishu = re.findall(r"Feishu upload summary: (\{[^}]+\})", tail)
    feishu_line = feishu[-1] if feishu else "（无）"
    running = bool(
        subprocess.run(
            ["pgrep", "-f", "pdfsummary.py"], capture_output=True
        ).stdout.strip()
    )

    body = "\n".join([
        f"日期：{today}",
        f"昨天文章数：{arts}",
        f"今日已入库汇总记录：{proc}",
        f"飞书上传：{feishu_line}",
        f"错误标记：{errors or '无'}",
    ])

    if running:
        status, subject = "INFO", f"【招聘汇总】{today} 仍在运行中"
        body += "\n\n8:30 的汇总进程还在运行，请稍后再确认。"
    elif arts == 0 and not errors:
        status, subject = "INFO", f"【招聘汇总】{today} 昨日无文章"
        body += "\n\n昨天没有抓到文章（可能是假期或数据源无更新），流程本身正常。"
    elif errors or (arts > 0 and proc == 0):
        status, subject = "FAIL", f"【招聘汇总】{today} 运行失败"
        body += "\n\n请检查 logs/summary.log 与 logs/backfill.log。"
    else:
        status, subject = "OK", f"【招聘汇总】{today} 运行成功"
        body += "\n\n今日汇总已正常发布（飞书表格 + 订阅邮件）。"

    send_email(subject, body, RECIPIENT, text_type="plain")
    print(f"[{status}] {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
