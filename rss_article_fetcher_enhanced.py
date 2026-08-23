#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS公众号文章爬取脚本（增强版）
从RSS地址获取公众号文章信息，存储到数据库中
支持增量更新、错误处理、日志记录和HTML转PDF功能
"""

import sqlite3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import re
import logging
import sys
import argparse
import os
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import json
import pdfkit
import hashlib
from pathlib import Path

# RSS源配置
PROJECT_DIR = Path(__file__).resolve().parent
RSS_URL = "file://" + str(PROJECT_DIR / "data" / "recruitment_feed.xml")
DB_PATH = str(PROJECT_DIR / "data" / "message_monitor.db")
PDF_DIR = str(PROJECT_DIR / "pdfs")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rss_fetcher_enhanced.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class RSSArticleFetcherEnhanced:
    def __init__(self, db_path=DB_PATH, rss_url=RSS_URL, pdf_dir=PDF_DIR):
        self.db_path = db_path
        self.rss_url = rss_url
        self.pdf_dir = Path(pdf_dir)
        self.pdf_dir.mkdir(exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # PDF生成配置
        self.pdf_options = {
            'page-size': 'A4',
            'margin-top': '0.75in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'encoding': "UTF-8",
            'no-outline': None,
            'enable-local-file-access': None,
            'load-error-handling': 'ignore',
            'load-media-error-handling': 'ignore'
        }

    def connect_db(self):
        """连接数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            # 新环境（Docker 空数据卷）幂等建表，与既有 schema 保持一致
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wechat_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    from_user TEXT,
                    title TEXT,
                    url TEXT UNIQUE,
                    summary TEXT,
                    cover_url TEXT,
                    content TEXT,
                    pdf_path TEXT,
                    images TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_data TEXT,
                    processed BOOLEAN DEFAULT FALSE,
                    process_time TIMESTAMP,
                    account_name TEXT,
                    pandora_processed BOOLEAN DEFAULT FALSE,
                    article_type TEXT
                )
            """)
            conn.commit()
            return conn
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise

    def fetch_rss(self):
        """获取RSS内容"""
        try:
            parsed = urlparse(self.rss_url)
            if parsed.scheme in ("", "file"):
                local_path = parsed.path if parsed.scheme == "file" else self.rss_url
                with open(local_path, "r", encoding="utf-8") as f:
                    content = f.read()
                logger.info(f"RSS获取成功(本地文件)，内容长度: {len(content)}")
                return content
            logger.info(f"正在获取RSS内容: {self.rss_url}")
            response = self.session.get(self.rss_url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'

            logger.info(f"RSS获取成功，内容长度: {len(response.text)}")
            return response.text
        except Exception as e:
            logger.error(f"RSS获取失败: {e}")
            raise

    def create_html_for_pdf(self, article_data):
        """为PDF生成创建格式化的HTML"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: "SimSun", serif; font-size: 14px; line-height: 1.6; margin: 20px; }}
                .header {{ border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 20px; }}
                .title {{ font-size: 20px; font-weight: bold; margin-bottom: 10px; }}
                .meta {{ color: #666; font-size: 12px; }}
                .content {{ margin-top: 20px; }}
                .content img {{ max-width: 100%; height: auto; }}
                .footer {{ border-top: 1px solid #ccc; margin-top: 30px; padding-top: 10px; font-size: 10px; color: #999; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="title">{title}</div>
                <div class="meta">
                    <strong>公众号:</strong> {account_name}<br>
                    <strong>发布时间:</strong> {created_at}<br>
                    <strong>原文链接:</strong> {url}
                </div>
            </div>
            <div class="content">
                {content_html}
            </div>
            <div class="footer">
                生成时间: {generated_at}<br>
                数据来源: RSS订阅<br>
                文章ID: {message_id}
            </div>
        </body>
        </html>
        """

        return html_template.format(
            title=article_data['title'] or 'Untitled',
            account_name=article_data['account_name'] or 'Unknown',
            created_at=article_data['created_at'] or 'Unknown',
            url=article_data['url'] or '#',
            content_html=article_data['raw_data'] or '<p>无内容</p>',
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            message_id=article_data['message_id'] or 'Unknown'
        )

    def generate_pdf_filename(self, article_data):
        """生成PDF文件名"""
        # 使用message_id和标题生成唯一文件名
        safe_title = re.sub(r'[^\w\u4e00-\u9fff]+', '_',
                            article_data['title'] or 'untitled')
        safe_title = safe_title[:50]  # 限制长度

        message_id = article_data['message_id'] or 'unknown'
        filename = f"{message_id}_{safe_title}.pdf"

        return self.pdf_dir / filename

    def html_to_pdf(self, article_data):
        """将文章HTML转换为PDF"""
        try:
            if not article_data['raw_data']:
                logger.warning(f"文章 {article_data['title']} 没有HTML内容，跳过PDF生成")
                return None

            # 生成HTML内容
            html_content = self.create_html_for_pdf(article_data)

            # 生成PDF文件路径
            pdf_path = self.generate_pdf_filename(article_data)

            # 如果PDF已存在，跳过生成
            if pdf_path.exists():
                logger.info(f"PDF已存在，跳过: {pdf_path.name}")
                return str(pdf_path)

            # 生成PDF
            logger.info(f"正在生成PDF: {pdf_path.name}")
            pdfkit.from_string(html_content, str(
                pdf_path), options=self.pdf_options)

            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                logger.info(
                    f"PDF生成成功: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")
                return str(pdf_path)
            else:
                logger.error(f"PDF生成失败: {pdf_path.name}")
                return None

        except Exception as e:
            logger.error(f"PDF生成过程出错: {e}")
            return None

    def parse_rss(self, rss_content):
        """解析RSS内容"""
        try:
            root = ET.fromstring(rss_content)
            items = []

            # 查找所有item
            for item in root.findall('.//item'):
                article_data = {}

                # 提取基本信息
                title_elem = item.find('title')
                article_data['title'] = title_elem.text if title_elem is not None else None

                link_elem = item.find('link')
                article_data['url'] = link_elem.text if link_elem is not None else None

                # dc:creator 需要使用命名空间
                creator_elem = item.find(
                    './/{http://purl.org/dc/elements/1.1/}creator')
                article_data['account_name'] = creator_elem.text if creator_elem is not None else None
                # 同样的值
                article_data['from_user'] = article_data['account_name']

                # guid作为message_id
                guid_elem = item.find('guid')
                article_data['message_id'] = guid_elem.text if guid_elem is not None else None

                # 发布时间
                pubdate_elem = item.find('pubDate')
                if pubdate_elem is not None:
                    try:
                        # 解析RSS时间格式：Sat, 19 Jul 2025 22:58:00 +0800
                        pubdate_str = pubdate_elem.text
                        # 移除时区信息简化解析
                        pubdate_clean = re.sub(
                            r'\s+[+-]\d{4}$', '', pubdate_str)
                        dt = datetime.strptime(
                            pubdate_clean, '%a, %d %b %Y %H:%M:%S')
                        article_data['created_at'] = dt.strftime(
                            '%Y-%m-%d %H:%M:%S')
                    except Exception as e:
                        logger.warning(f"时间解析失败: {pubdate_elem.text}, 错误: {e}")
                        article_data['created_at'] = datetime.now().strftime(
                            '%Y-%m-%d %H:%M:%S')
                else:
                    article_data['created_at'] = datetime.now().strftime(
                        '%Y-%m-%d %H:%M:%S')

                # 描述内容 (HTML)
                desc_elem = item.find('description')
                if desc_elem is not None and desc_elem.text:
                    raw_data = desc_elem.text
                else:
                    # 兜底：部分 RSS 源正文放在 content:encoded
                    content_elem = item.find(
                        '{http://purl.org/rss/1.0/modules/content/}encoded')
                    raw_data = content_elem.text if content_elem is not None else None
                article_data['raw_data'] = raw_data
                # 从HTML中提取纯文本
                article_data['content'] = self.extract_text_from_html(
                    raw_data) if raw_data else None

                # 设置默认值
                article_data['processed'] = False
                article_data['pandora_processed'] = False
                article_data['article_type'] = 'wechat'
                article_data['summary'] = None
                article_data['cover_url'] = None
                article_data['pdf_path'] = None  # 稍后生成PDF时更新
                article_data['images'] = None
                article_data['process_time'] = None

                # 验证必要字段
                if article_data['message_id'] and article_data['title']:
                    items.append(article_data)
                    logger.debug(f"解析文章: {article_data['title'][:50]}...")
                else:
                    logger.warning(f"跳过无效文章，缺少必要字段: {article_data}")

            logger.info(f"成功解析 {len(items)} 篇文章")
            return items

        except ET.ParseError as e:
            logger.error(f"RSS XML解析失败: {e}")
            raise
        except Exception as e:
            logger.error(f"RSS解析过程出错: {e}")
            raise

    def extract_text_from_html(self, html_content):
        """从HTML中提取纯文本内容"""
        if not html_content:
            return None

        try:
            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # 移除script和style标签
            for script in soup(["script", "style"]):
                script.decompose()

            # 获取纯文本
            text = soup.get_text()

            # 清理多余的空白
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip()
                      for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)

            return text[:5000] if text else None  # 限制长度

        except Exception as e:
            logger.warning(f"HTML文本提取失败: {e}")
            return html_content[:1000] if html_content else None

    def get_existing_ids_and_urls(self, conn):
        """获取数据库中已存在的message_id与url集合（url 用于去重兜底）"""
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message_id, url FROM wechat_articles WHERE message_id IS NOT NULL")
            rows = cursor.fetchall()
            existing_ids = {row[0] for row in rows}
            existing_urls = {row[1] for row in rows if row[1]}
            logger.info(f"数据库中已有 {len(existing_ids)} 篇文章")
            return existing_ids, existing_urls
        except Exception as e:
            logger.error(f"获取已存在文章ID失败: {e}")
            return set(), set()

    def process_articles_with_pdf(self, articles):
        """处理文章并生成PDF"""
        processed_articles = []

        for article in articles:
            try:
                # 生成PDF
                pdf_path = self.html_to_pdf(article)
                article['pdf_path'] = pdf_path

                processed_articles.append(article)

            except Exception as e:
                logger.error(f"处理文章 {article['title']} 时出错: {e}")
                # 即使PDF生成失败，也保存文章数据
                article['pdf_path'] = None
                processed_articles.append(article)

        return processed_articles

    def insert_articles(self, conn, articles):
        """批量插入文章到数据库"""
        if not articles:
            logger.info("没有新文章需要插入")
            return 0

        try:
            cursor = conn.cursor()

            insert_sql = """
                INSERT INTO wechat_articles (
                    message_id, from_user, title, url, summary, cover_url, 
                    content, pdf_path, images, created_at, raw_data, 
                    processed, process_time, account_name, pandora_processed, article_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            insert_data = []
            for article in articles:
                insert_data.append((
                    article['message_id'],
                    article['from_user'],
                    article['title'],
                    article['url'],
                    article['summary'],
                    article['cover_url'],
                    article['content'],
                    article['pdf_path'],
                    article['images'],
                    article['created_at'],
                    article['raw_data'],
                    article['processed'],
                    article['process_time'],
                    article['account_name'],
                    article['pandora_processed'],
                    article['article_type']
                ))

            cursor.executemany(insert_sql, insert_data)
            conn.commit()

            inserted_count = cursor.rowcount
            logger.info(f"成功插入 {inserted_count} 篇新文章")
            return inserted_count

        except Exception as e:
            logger.error(f"文章插入失败: {e}")
            conn.rollback()
            raise

    def run(self, dry_run=False, skip_pdf=False):
        """运行RSS爬取流程"""
        try:
            logger.info("=== RSS文章爬取开始（增强版） ===")

            # 1. 获取RSS内容
            rss_content = self.fetch_rss()

            # 2. 解析RSS
            articles = self.parse_rss(rss_content)

            if not articles:
                logger.info("没有解析到任何文章")
                return

            # 3. 连接数据库
            with self.connect_db() as conn:

                # 4. 获取已存在的文章ID与URL（增量更新，URL 兜底去重）
                existing_ids, existing_urls = self.get_existing_ids_and_urls(conn)

                # 5. 筛选新文章
                new_articles = [
                    article for article in articles
                    if article['message_id'] not in existing_ids
                    and article.get('url') not in existing_urls
                ]

                logger.info(
                    f"总共解析 {len(articles)} 篇文章，其中 {len(new_articles)} 篇是新文章")

                if dry_run:
                    logger.info("=== DRY RUN 模式，不实际插入数据库 ===")
                    for article in new_articles[:3]:  # 只显示前3篇
                        logger.info(
                            f"新文章: {article['title']} | {article['account_name']} | {article['created_at']}")
                    return

                if not new_articles:
                    logger.info("没有新文章需要处理")
                    return

                # 6. 处理文章并生成PDF
                if not skip_pdf:
                    logger.info("开始生成PDF文件...")
                    new_articles = self.process_articles_with_pdf(new_articles)
                else:
                    logger.info("跳过PDF生成")

                # 7. 插入新文章
                inserted_count = self.insert_articles(conn, new_articles)

                pdf_count = sum(
                    1 for article in new_articles if article.get('pdf_path'))
                logger.info(
                    f"=== RSS文章爬取完成，新增 {inserted_count} 篇文章，生成 {pdf_count} 个PDF ===")

        except Exception as e:
            logger.error(f"RSS爬取流程失败: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description='RSS公众号文章爬取脚本（增强版）')
    parser.add_argument('--dry-run', action='store_true',
                        help='试运行模式，不实际插入数据库')
    parser.add_argument('--skip-pdf', action='store_true', help='跳过PDF生成')
    parser.add_argument('--rss-url', default=RSS_URL, help='RSS地址')
    parser.add_argument('--db-path', default=DB_PATH, help='数据库路径')
    parser.add_argument('--pdf-dir', default=PDF_DIR, help='PDF保存目录')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 创建并运行爬取器
    fetcher = RSSArticleFetcherEnhanced(
        db_path=args.db_path,
        rss_url=args.rss_url,
        pdf_dir=args.pdf_dir
    )

    try:
        fetcher.run(dry_run=args.dry_run, skip_pdf=args.skip_pdf)
    except KeyboardInterrupt:
        logger.info("用户中断执行")
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
