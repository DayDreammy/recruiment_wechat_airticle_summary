#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从本机 wechat2rss (127.0.0.1:8081) 聚合全部订阅为单一 RSS，
输出格式兼容原远程 query.php 聚合源：
  - guid: 由原文链接派生的稳定 ID（用于抓取器去重 / PDF 文件名）
  - dc:creator: 公众号名称
  - description: 全文 HTML（图片 URL 改写到本机 img-proxy）
输出文件由环境变量 WECHAT2RSS_FEED_PATH 指定，默认 data/recruitment_feed.xml。
"""

import hashlib
import logging
import os
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "recruitment_feed.xml"

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
DC_NS = "http://purl.org/dc/elements/1.1/"
ATOM_NS = "http://www.w3.org/2005/Atom"

REMOTE_WECHAT2RSS_HOSTS = (
    "http://47.99.121.125:8081",
    "https://47.99.121.125:8081",
)


def text_of(item, tag):
    el = item.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def rewrite_images(html, local_base):
    """把正文里指向远程 wechat2rss img-proxy 的图片地址改到本机。"""
    if not html:
        return html
    for host in REMOTE_WECHAT2RSS_HOSTS:
        html = html.replace(host, local_base)
    return html


def fetch_feed_items(base, token, feed):
    """抓取单个订阅源并返回归一化条目列表（每线程独立 session，便于并发）。"""
    fid = feed.get("id")
    name = (feed.get("name") or "").strip()
    if not fid or not name:
        return []
    session = requests.Session()
    session.headers.update({"User-Agent": "recruiment-feed-builder/1.0"})
    try:
        feed_resp = session.get(
            f"{base}/feed/{fid}.xml", params={"k": token}, timeout=25)
        feed_resp.raise_for_status()
    except Exception as e:
        logging.warning(f"获取 feed 失败: {name}: {e}")
        return []
    try:
        root = ET.fromstring(feed_resp.text)
    except Exception as e:
        logging.warning(f"解析 feed 失败: {name}: {e}")
        return []

    out = []
    for item in root.findall(".//item"):
        title = text_of(item, "title")
        link = text_of(item, "link")
        pubdate = text_of(item, "pubDate")
        if not title or not link:
            continue
        content_el = item.find(f"{{{CONTENT_NS}}}encoded")
        html = ""
        if content_el is not None and content_el.text:
            html = content_el.text
        else:
            html = text_of(item, "description")
        guid = hashlib.sha1(link.encode("utf-8")).hexdigest()
        out.append({
            "title": title,
            "link": link,
            "guid": guid,
            "pubdate": pubdate,
            "pub_dt": parse_pubdate(pubdate),
            "creator": name,
            "html": rewrite_images(html, base),
        })
    return out


def parse_pubdate(pubdate_str):
    if not pubdate_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(pubdate_str)
        return dt or datetime.min.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def build_xml(items):
    ET.register_namespace("dc", DC_NS)
    ET.register_namespace("content", CONTENT_NS)
    ET.register_namespace("atom", ATOM_NS)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "wechat2rss"
    ET.SubElement(channel, "link").text = "http://127.0.0.1:8081/"
    ET.SubElement(channel, "description").text = "wechat2rss 的订阅源（本地聚合）"
    ET.SubElement(channel, "pubDate").text = datetime.now().strftime(
        "%a, %d %b %Y %H:%M:%S %z")

    for it in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = it["title"]
        ET.SubElement(item, "link").text = it["link"]
        ET.SubElement(item, "guid").text = it["guid"]
        ET.SubElement(item, "pubDate").text = it["pubdate"]
        ET.SubElement(item, f"{{{DC_NS}}}creator").text = it["creator"]
        ET.SubElement(item, "description").text = it["html"]

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    base = os.getenv("WECHAT2RSS_BASE", "http://127.0.0.1:8081").rstrip("/")
    token = os.getenv("WECHAT2RSS_RSS_TOKEN", "").strip()
    output_path = Path(os.getenv("WECHAT2RSS_FEED_PATH", str(DEFAULT_OUTPUT)))
    try:
        max_items = int(os.getenv("RECRUIT_FEED_MAX_ITEMS", "300"))
    except ValueError:
        max_items = 300

    if not token:
        logging.error("未配置 WECHAT2RSS_RSS_TOKEN，无法读取本机 wechat2rss")
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": "recruiment-feed-builder/1.0"})

    try:
        resp = session.get(f"{base}/list", params={"k": token}, timeout=20)
        resp.raise_for_status()
        payload = resp.json() or {}
        feeds = payload.get("feeds") or payload.get("data") or []
        if not isinstance(feeds, list):
            feeds = []
    except Exception as e:
        logging.error(f"获取 wechat2rss /list 失败: {e}")
        return 1
    logging.info(f"本机 wechat2rss 订阅数: {len(feeds)}")

    items = []
    errors = 0
    workers = int(os.getenv("RECRUIT_FEED_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(fetch_feed_items, base, token, feed)
            for feed in feeds
        ]
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception as e:
                errors += 1
                logging.warning(f"抓取 feed 异常: {e}")

    if not items:
        logging.error(f"聚合结果为空（错误 feed 数 {errors}），保留原 feed 文件")
        return 1

    items.sort(key=lambda it: it["pub_dt"], reverse=True)
    items = items[:max_items]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_xml(items))
    logging.info(
        f"聚合完成: {len(items)} 条（错误 {errors}），写入 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
