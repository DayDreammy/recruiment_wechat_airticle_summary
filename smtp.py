import smtplib
import os
import re
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 邮箱配置信息
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.163.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER_NAME = os.getenv("SMTP_SENDER_NAME", "微秘Daily")
EMAIL_ADDRESS = os.getenv("SMTP_EMAIL", "daydreammy@163.com")
EMAIL_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# 招聘信息的邮件主题和内容 (主题要带上日期)
RECRUITMENT_SUBJECT = f"Pandora招聘信息总结 - {datetime.now().strftime('%Y-%m-%d')}"
RECRUITMENT_BODY = """
亲爱的朋友：

您好！

Pandora招聘信息总结今日已更新，请查收附件。

---

Pandora招聘信息总结是一个公益项目，
诞生于浙江大学工程师学院职业发展协会招聘信息分享工作组，
致力于每日汇总和整理浙大就业、北大未名俱乐部等招聘类公众号的优质内容。
本项目于23年12月中旬开始内测，并于23年4月份正式上线，至今不断迭代更新。

我们的终极愿景是 “让信息更加顺畅的流动 + 有个秘书帮忙处理过载信息”。

项目地址：https://jobs.daydreammy.xyz
投稿：欢迎企业HR、校招负责人及校园大使投稿，详情请见项目主页。
交流群：系统维护和更新会第一时间发布在交流群（QQ群：442041683），欢迎进群交流。

我们期待您的宝贵建议，也欢迎加入我们一起改变世界！

感谢您的支持与关注！
祝好，
浙大工院职业发展协会
招聘信息分享工作组
Daydreamer
"""

# 定义期望的公众号顺序
ORDER_TEXT = """
浙大就业
浙江大学学生基层工作服务协会
未名俱乐部
浙大职协SCDA
清华就业
北大就业
南大就业
人大就业
国科大毕业生就业指导中心
浙江引才
材必实习校招
嗖嗖实习校招
国聘
500强校园招聘
高校人才网
人才引进助手
成功就业
本地宝上海招聘
京师就业
艺术招聘
四川人才
商科求职
日常实习
杭州国企招聘
银行求职考试网
投行咨询求职
本硕博高层次引进人才
双一流高层次人才引进
青年校招
博士人才网
刺猬实习校招
华为杭厦招聘
华为招聘
OPPO招聘
阿里巴巴集团招聘
offer先生
DJI大疆招聘
字节跳动招聘
比亚迪招聘
小米招聘
百度招聘
美团招聘
拼多多招聘
实习僧
Candy实习吧
事业求职网
金融求职报
国聘通
冀人事人才职聘网
翰德Hudson
UniCareer
青年校招
500强校招实习
早实习
事业单位招聘考试信息平台
国企求职
留学求职网
求职家
今日实习
Finacc实习求职
事务所实习信息
金砖实习
国企央企名企招聘丨互联派
线上实习
暑期实习网
四大实习
爱思益求职
经济观察报
PaperWeekly
    """

# 清理文本并生成有序的公众号列表
# 1. .strip() 去除整个文本块前后的空白
# 2. .split('\n') 按行分割
# 3. line.strip() 去除每一行前后的空白
# 4. if line.strip() 过滤掉所有空行
ORDERED_ACCOUNTS = [line.strip()
                    for line in ORDER_TEXT.strip().split('\n') if line.strip()]

# 创建一个干净的、从公众号名称到其排序索引的映射
ORDER_MAP = {account: i for i, account in enumerate(ORDERED_ACCOUNTS)}


def send_email(subject, body, recipient_email, text_type='plain'):
    """
    发送邮件的函数
    :param subject: 邮件主题
    :param body: 邮件内容
    :param recipient_email: 收件人邮箱
    """
    try:
        # 创建邮件内容
        msg = MIMEMultipart()
        msg['From'] = formataddr((SENDER_NAME, EMAIL_ADDRESS))
        msg['To'] = formataddr(("Recipient", recipient_email))
        msg['Subject'] = subject

        # 邮件正文
        msg.attach(MIMEText(body, text_type, 'utf-8'))

        if not EMAIL_PASSWORD:
            logging.error("SMTP_PASSWORD 未配置，跳过发送")
            return

        # 使用SMTP连接发送邮件
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, [recipient_email], msg.as_string())
            logging.info(f"邮件已成功发送到 {recipient_email}")
    except Exception as e:
        logging.error(f"发送邮件失败: {e}")


def test_send_email():
    try:
        subject = "测试邮件"
        body = "这是一封测试邮件，来自 Python 程序。"
        recipient_email = "1781051483@qq.com"  # 替换为目标收件人邮箱
        send_email(subject, body, recipient_email)
    except Exception as e:
        logging.error(f"测试发送邮件失败: {e}")

# 发送文件到指定邮箱


def send_email_file(subject, body, recipient_email, file_path):
    """
    发送邮件的函数
    :param subject: 邮件主题
    :param body: 邮件内容
    :param recipient_email: 收件人邮箱
    :param file_path: 附件路径
    """
    try:
        # 创建邮件内容
        msg = MIMEMultipart()
        msg['From'] = formataddr((SENDER_NAME, EMAIL_ADDRESS))
        msg['To'] = formataddr(("Recipient", recipient_email))
        msg['Subject'] = subject

        # 邮件正文
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # 添加附件
        with open(file_path, 'rb') as f:
            attachment = MIMEText(f.read(), 'base64', 'utf-8')
            attachment["Content-Type"] = 'application/octet-stream'
            attachment.add_header('Content-Disposition', 'attachment',
                                  filename=('gbk', '', file_path.split('/')[-1]))
            msg.attach(attachment)

        if not EMAIL_PASSWORD:
            logging.error("SMTP_PASSWORD 未配置，跳过发送")
            return

        # 使用SMTP连接发送邮件
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, [recipient_email], msg.as_string())
            logging.info(f"邮件已成功发送到 {recipient_email}")
    except Exception as e:
        logging.error(f"发送邮件失败: {e}")


def test_send_email_file(file_path=None):
    try:
        subject = RECRUITMENT_SUBJECT
        body = RECRUITMENT_BODY
        recipient_email = "1781051483@qq.com"  # 替换为目标收件人邮箱
        if not file_path:
            file_path = r"/home/yy/project/recruiment_article_summary/example.log"
        send_email_file(subject, body, recipient_email, file_path)
    except Exception as e:
        logging.error(f"测试发送邮件失败: {e}")


def send_email_files_to_recipients(file_path, recipient_emails):
    """
    发送多个文件到多个邮箱
    :param file_paths: 文件路径列表
    :param recipient_emails: 收件人邮箱列表
    """
    try:
        subject = RECRUITMENT_SUBJECT
        body = RECRUITMENT_BODY
        for recipient_email in recipient_emails:
            send_email_file(subject, body, recipient_email, file_path)
    except Exception as e:
        logging.error(f"发送邮件失败: {e}")


def construct_personal_email_content(articles):
    """
    构造个性化邮件内容：标题超链接 + 精简纯文本摘要（无 Markdown，换行正常渲染）
    :param articles: 文章列表
    :return: 邮件内容
    """

    def clean_summary(text):
        """去掉摘要里的 Markdown 残留，避免在邮件里显示成 ** 等符号。"""
        text = text or ""
        text = re.sub(r"\*\*|`|#{1,6}", "", text)
        text = re.sub(r"^[\s]*[-*•]\s+", "", text, flags=re.M)
        text = re.sub(r"总结内容[:：]?\s*", "", text)
        return text.strip()

    personal_email_content = f"""
    <html>
    <body>
        <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">尊敬的用户：</p>
        <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">以下是您订阅的公众号昨日文章总结（共 {len(articles)} 篇），请查收：</p>
        <ul>
    """

    # 文章重排序
    articles.sort(key=lambda article: ORDER_MAP.get(
        article.account.strip(), len(ORDER_MAP)))

    # 遍历每篇文章，构造邮件内容
    for idx, article in enumerate(articles, start=1):
        try:
            summary = clean_summary(article.processed_summary)[:500]
        except Exception:
            summary = ""
        summary_html = html.escape(summary) if summary else "（无摘要）"

        personal_email_content += f"""
        <li style="list-style:none; margin: 12px 0; padding: 12px 14px; background:#f7f8fa; border-radius:8px; font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;">
            <div style="font-size:15px; font-weight:600; color:#111;">
                {idx}. {html.escape(article.account or '')}
                · <a href="{article.content_url}" style="color:#1a73e8; text-decoration:none;">{html.escape(article.title or '')}</a>
            </div>
            <div style="margin-top:6px; font-size:13px; color:#444; line-height:1.7; white-space:pre-line;">{summary_html}</div>
        </li>
        """

    # 邮件结束语
    personal_email_content += """
    </ul>
    <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">感谢您的阅读，祝您一天愉快！</p>
    <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">如有问题或建议，欢迎与我们联系（交流QQ群：442041683）。</p>

    <hr>

    <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">本项目招聘信息 Demo：<a href="https://jobs.daydreammy.xyz" target="_blank">Pandora 招聘信息分享</a></p>

    <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">我们的终极愿景是 “让信息更加顺畅的流动 + 用优质输入建立深刻认知”。</p>

    <p style="font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color:#333;">此致，<br>Daydreamer</p>
    </body>
    </html>
    """

    return personal_email_content


# 测试函数
if __name__ == "__main__":
    # test_send_email()
    test_send_email_file()
