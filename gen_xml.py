from common import read_config
from sqldb import get_user_subscribed_accounts_processed_articles
import xml.etree.ElementTree as ET
from datetime import datetime, date
import pytz
from xml.sax.saxutils import escape
import logging
import subprocess

from up2feishu import fetch_user_info_from_feishu_and_update_database

logger = logging.getLogger("pdfsummary")


def get_pub_date(article):
    pub_date = getattr(article, 'publish_date', datetime.now(pytz.utc))

    # 如果pub_date是date类型而非datetime，转换为datetime
    if isinstance(pub_date, date) and not isinstance(pub_date, datetime):
        pub_date = datetime.combine(pub_date, datetime.min.time())

    # 确保有时区信息
    if not pub_date.tzinfo:
        pub_date = pub_date.replace(tzinfo=pytz.utc)
    else:
        pub_date = pub_date.astimezone(pytz.utc)

    return pub_date.strftime("%a, %d %b %Y %H:%M:%S GMT")


def generate_rss(articles, output_path="data/rss.xml"):
    rss = ET.Element("rss",
                     version="2.0",
                     attrib={"xmlns:atom": "http://www.w3.org/2005/Atom"}
                     )
    channel = ET.SubElement(rss, "channel")

    # Atom 自引用链接
    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("href", "https://yourdomain.com/rss.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    ET.SubElement(channel, "title").text = "微秘 Daily"
    ET.SubElement(channel, "link").text = "https://yourdomain.com"
    ET.SubElement(
        channel, "description").text = "我们的终极愿景是 “让信息更加顺畅的流动 + 用优质输入建立底层认知”。"
    ET.SubElement(channel, "language").text = "zh-cn"

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article.title
        ET.SubElement(item, "link").text = article.content_url

        description = f"{article.account}：{article.processed_summary}..."
        ET.SubElement(item, "description").text = escape(description)

        ET.SubElement(item, "guid").text = article.content_url
        ET.SubElement(item, "pubDate").text = get_pub_date(article)

    ET.indent(rss, space="\t")
    tree = ET.ElementTree(rss)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def update_upload_xml(xml_file_path):
    """
    Upload the generated XML file to remote server using scp
    """
    try:
        remote_path = "root@146.190.1.64:/var/www/rss_feeds/"
        cmd = ["scp", "-i", "~/.ssh/DOkey", xml_file_path, remote_path]

        result = subprocess.run(cmd,
                                capture_output=True,
                                text=True,
                                check=True)

        if result.returncode == 0:
            logger.info(
                f"Successfully uploaded {xml_file_path} to remote server")
        else:
            logger.error(f"Failed to upload {xml_file_path}: {result.stderr}")

    except subprocess.CalledProcessError as e:
        logger.exception(f"Error uploading file {xml_file_path}: {str(e)}")
    except Exception as e:
        logger.exception(
            f"Unexpected error uploading file {xml_file_path}: {str(e)}")


def gen_and_update_xml(email, articles):
    email_filename = email.replace(
        '@', '_at_').replace('.', '_dot_')
    xml_file_path = f"/home/yy/project/recruiment_article_summary/data/{email_filename}_rss.xml"
    generate_rss(
        articles, output_path=xml_file_path)
    update_upload_xml(xml_file_path)


def fetch_and_update_xml(users_info=None):
    try:
        email_list = [user.email for user in users_info]

        for email in email_list:
            try:
                articles = get_user_subscribed_accounts_processed_articles(
                    email, only_today=True)
                gen_and_update_xml(email=email, articles=articles)
            except Exception as e:
                logger.exception(f"发送邮件失败: {e}, email: {email}")

    except Exception as e:
        logger.exception(f"发送邮件失败: {e}")


# 使用示例
if __name__ == "__main__":
    # 假设从数据库获取当天文章列表
    # email = '1781051483@qq.com'
    # articles = get_user_subscribed_accounts_processed_articles(
    #     email, only_today=True)
    # generate_rss(articles)
    # print("RSS 文件已生成！")
    config_path = "config.json"
    config = read_config(config_path)
    users_info = fetch_user_info_from_feishu_and_update_database(config)
    fetch_and_update_xml(users_info)
