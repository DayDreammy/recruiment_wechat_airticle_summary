import os
import random
import sys
import io
import re
from itertools import islice
import csv
import json
from datetime import datetime, timedelta
import time
import threading

import fitz  # PyMuPDF
from PIL import Image


import os
from datetime import datetime

try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception:
    PaddleOCR = None
    PADDLE_AVAILABLE = False

import logging


from bot import OpenaiBot
from common import csv_columns
from gen_xml import gen_and_update_xml
from prompts import PromptManager
from up2table_backend import upload_recruitment_table, fetch_user_info_and_update_database
from csv2excel import csv_to_excel
from up2airtable import upload_to_airtable
from common import read_config

from smtp import send_email_file, send_email_files_to_recipients, send_email, construct_personal_email_content

from sqldb import get_today_and_yesterday_file_paths, insert_processed_article, update_processed_article, fetch_processed_articles_by_id, get_user_subscribed_accounts_processed_articles, fetch_processed_articles_by_type, process_user_batch, fetch_unprocessed_articles, mark_article_processed, batch_update_article_types, fetch_articles_by_type

from concurrent.futures import ThreadPoolExecutor
from typing import List

PROJECT_ROOT = os.getenv(
    "PDFSUMMARY_PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))


def read_int_env(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logging.getLogger("pdfsummary").warning(
            f"Ignore invalid {name}={value}, fallback to {default}")
        return default


# create logs folder if not exists
log_dir = os.getenv("PDFSUMMARY_LOG_DIR", os.path.join(PROJECT_ROOT, "logs"))
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# use current date as log file name
current_date = datetime.now().strftime('%Y-%m-%d')
log_file_name = f'{current_date}.log'
log_file_path = os.path.join(log_dir, log_file_name)


# 自定义Logger
logger = logging.getLogger("pdfsummary")
logger.setLevel(logging.DEBUG)  # 明确设置自定义Logger的级别

# 创建一个文件Handler
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# 创建一个标准输出StreamHandler
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# 添加Handlers到自定义Logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# 测试Logger
logger.debug("This is a debug message")


# prompts = Prompts()
# summary_prompt = prompts.summary_prompt
# judge_prompt = prompts.judge_prompt
# extract_prompt = prompts.extract_prompt

prompts_pool = PromptManager()


# Define your thresholds here
ocr_text_len_threshold = 300
max_gpt_input_len = 100000
direct_summary_max_len = read_int_env("LLM_DIRECT_SUMMARY_MAX_CHARS", 800000)
sleep_time_min = 0  # seconds
sleep_time_max = 2  # seconds

# supported llm, other llms suggest to use oneapi etc.
llm_model_list = ["openai", "zhipu", "deepseek"]


###
# pdf functions
###
def extract_text_from_first_page(pdf_path):
    try:
        with fitz.open(pdf_path) as pdf:
            # 提取第一页的文本
            text = pdf[0].get_text()
        return text
    except Exception as e:
        logger.exception(f"提取第一页的文本失败: {e}")
        return None


def extract_text_from_all_pages(pdf_path):
    try:
        with fitz.open(pdf_path) as pdf:
            # 提取所有页面的文本
            text = ""
            for page in pdf:
                text += page.get_text()
        return text
    except Exception as e:
        logger.exception(f"提取所有页面的文本失败: {e}")
        return None


def extract_link_after_text(pdf_path, search_text="原文地址"):
    try:
        with fitz.open(pdf_path) as pdf:
            # 我们只搜索第一页
            page = pdf[0]
            text_instances = page.search_for(search_text)

            # 检查是否找到了搜索文本
            if len(text_instances) > 0:
                # 取搜索文本的第一个实例
                text_instance = text_instances[0]
                # 获取页面的链接列表
                links = page.get_links()
                # 搜索位于特定文本实例之后的链接
                for link in links:
                    if link['kind'] == 2:
                        # 返回找到的第一个链接
                        return link['uri']
        return None
    except Exception as e:
        logger.exception(f"提取链接失败: {e}")
        return None


def extract_metadata(text):
    title_pattern = r'原文地址：(.*?)\n'
    account_pattern = r'公号:(.*?)\s'
    time_pattern = r'发布时间:(\d{4}-\d{2}-\d{2})'

    try:
        title = re.search(title_pattern, text).group(
            1) if re.search(title_pattern, text) else ""
        account = re.search(account_pattern, text).group(
            1) if re.search(account_pattern, text) else ""
        publish_date = re.search(time_pattern, text).group(
            1) if re.search(time_pattern, text) else ""
    except Exception as e:
        logger.exception(f"提取元数据失败: {e}")
        return None, None, None

    return title, account, publish_date


def pdf_to_images(pdf_path, output_folder=None, image_format="jpeg"):
    """
    将 PDF 文件的每一页转换为图像，并保存到指定文件夹。

    Args:
        pdf_path: PDF 文件的路径。
        output_folder:  保存图像的文件夹路径。如果为 None，则在 PDF 所在目录下创建同名文件夹。
        image_format: 图像格式，如 "png", "jpg", "jpeg" 等。

    Returns:
        一个列表，包含所有生成的图像文件的路径。
    """

    # 1. 创建输出文件夹（如果需要）
    if output_folder is None:
        output_folder = os.getenv(
            "PDFSUMMARY_TMP_DIR", os.path.join(PROJECT_ROOT, "tmp"))
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 2. 打开 PDF 文件
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF file: {e}")
        return []  # 发生错误，返回空列表

    image_paths = []

    # 3. 遍历每一页
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)

        # 4.  渲染页面为 Pixmap (像素图)
        #    get_pixmap() 参数：
        #    - matrix: 缩放和旋转。  fitz.Identity 保持原样。
        #    - dpi:  分辨率（dots per inch）。  越大图像越清晰，文件也越大。
        #    - colorspace:  颜色空间。  fitz.csRGB (默认) 或 fitz.csGRAY (灰度)。
        #    - alpha:  是否包含透明通道 (True/False)。  对于 PNG 很有用。
        pix = page.get_pixmap(matrix=fitz.Identity, dpi=300,
                              colorspace=fitz.csRGB, alpha=False)

        # 5.  构建图像文件名
        # 04d: 4位数字，不足补零
        image_name = f"page_{page_num + 1:04d}.{image_format}"
        image_path = os.path.join(output_folder, image_name)

        # 6. 保存图像
        try:
            pix.save(image_path)
            image_paths.append(image_path)
        except Exception as e:
            print(f"Error saving image {image_name}: {e}")
            #  可以选择是否继续处理其他页面 (这里选择继续)

    doc.close()  # 关闭 PDF 文件
    return image_paths


def gemini_ocr_pdf(pdf_path):
    img_paths = pdf_to_images(pdf_path)
    config = read_config(os.getenv(
        "PDFSUMMARY_CONFIG", os.path.join(PROJECT_ROOT, "config.json")))
    try:
        base_url = config.get("uni_api_base_url")
        api_key = config.get("uni_api_key")
        # model = "gemini-2.0-flash"
        models = ["gemini-2.0-flash", "gemini-2.0-pro-exp-02-05",
                  "gemini-1.5-pro", "gemini-2.0-flash-lite-preview-02-05",
                  "gemini-exp-1206"]
        model = random.choice(models)

        bot = OpenaiBot(api_key=api_key, base_url=base_url, model=model)

        answer = bot.get_response("",
                                  "请准确地提取所有给定公众号截图中的信息，重点关注其中的图片内容",
                                  img_paths=img_paths)

        logger.info(f"gemini {model} ocr info : \n{answer}\n ")

        return answer
    except:
        return ""


_ocr_engine = None
_ocr_lock = threading.Lock()


def _get_ocr_engine():
    """懒加载 PaddleOCR 3.x 引擎（旧版 use_gpu/show_log 参数已移除）。"""
    global _ocr_engine
    if not PADDLE_AVAILABLE:
        return None
    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(lang="ch", use_textline_orientation=True)
    return _ocr_engine


def paddle_ocr_pdf(pdf_path):
    text = []
    if not pdf_path or not os.path.exists(pdf_path):
        logger.warning(f"OCR 跳过：PDF 不存在 {pdf_path}")
        return ""
    try:
        ocr = _get_ocr_engine()
        if ocr is None:
            logger.warning("PaddleOCR 未安装（Docker 精简镜像），跳过 OCR")
            return ""
        # PaddleOCR 3.x 并发 predict 需要串行化
        with _ocr_lock:
            result = ocr.predict(pdf_path)
        for res in result or []:
            rec_texts = res.get("rec_texts") or []
            text.extend(rec_texts)
    except Exception as e:
        logger.exception(f"提取PDF文本失败: {e}")

    # 将所有页面的文本连接成一个长字符串
    ocr_text_all = "\n".join(text)
    logger.info(f"ocr text:\n {ocr_text_all}")
    return ocr_text_all


def split_text(text, max_length=max_gpt_input_len):
    """将文本分割成不超过max_length的多个部分"""
    if not text:
        return []
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]


def is_article_recruitment(text, bot=None):
    """判断文本是否是招聘信息"""
    judge = "0"
    if bot is None:
        return True

    judge = bot.get_response(judge_prompt, text, show_log=True)

    if judge == "1":
        return True
    elif judge == "":
        return True
    elif "1" in judge:
        return True
    else:
        return False


def summarize_article(text, bot=None, summary_prompt="总结下列文本内容"):
    """
    Summarizes the given text.

    DeepSeek is used as the primary model and supports very long context, so
    normal articles are summarized in one request. Splitting is kept only as a
    fallback for unusually large inputs or providers with smaller windows.

    Args:
        text (str): The text to be summarized.

    Returns:
        str: The summary of the text.
    """
    if bot is None:
        return ""

    text = text or ""
    if not text.strip():
        logger.warning("Skip summarization because article text is empty")
        return ""

    if len(text) <= direct_summary_max_len:
        final_summary = bot.get_response(summary_prompt, text)
    else:
        logger.warning(
            f"Article text length={len(text)} exceeds direct summary limit={direct_summary_max_len}; "
            f"fall back to chunked summarization")
        parts = split_text(text)
        summaries = [
            bot.get_response(summary_prompt, part)
            for part in parts
            if part and part.strip()
        ]
        summaries = [summary for summary in summaries if summary]
        integrated_summary = ' '.join(summaries)
        final_summary = integrated_summary

        if len(parts) > 1 and integrated_summary:
            if len(integrated_summary) > direct_summary_max_len:
                integrated_summary = integrated_summary[:direct_summary_max_len]
            final_summary = bot.get_response(summary_prompt, integrated_summary)

    if final_summary != '':
        end_line = f"\n\n(Powered by {bot.model}, 请以原文为准。)"
        final_summary += end_line

    logger.info(f"Summary: {final_summary}")

    return final_summary


def parse_time(time_str):
    # 尝试匹配日期范围
    range_match = re.match(
        r"(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})", time_str)
    if range_match:
        start, end = range_match.groups()
        return {"开始": start, "结束": end}

    # 尝试匹配单个日期
    single_match = re.match(r"\d{4}-\d{2}-\d{2}", time_str)
    if single_match:
        return {"日期": time_str}

    # 如果格式不符，返回原始字符串
    return {"原始字符串": time_str}


def extract_json(text):
    # 正则表达式，其中报名时间部分更通用
    pattern = r"招聘批次: (.*)\n工作地点: (.*)\n报名时间: (.*?)\n岗位类别: (.*)"

    match = re.search(pattern, text)
    if match:
        batch, location, time_str, category = match.groups()

        # 解析报名时间
        time_data = parse_time(time_str)

        data = {
            "招聘批次": batch,
            "工作地点": location,
            "报名时间": time_data,
            "岗位类别": category
        }

        return json.dumps(data, ensure_ascii=False)
    else:
        return "无法匹配文本格式"


def extract_key_info(text, bot=None, extract_prompt="提取关键信息"):
    batch = ""
    location = ""
    time_info = ""
    category = ""
    json_data = None

    if bot is None:
        return batch, location, time_info, category, json_data

    text = text or ""
    if not text.strip():
        logger.warning("Skip key info extraction because summary text is empty")
        return batch, location, time_info, category, json_data

    output = bot.get_response(extract_prompt, text)
    if not output:
        logger.warning("Skip key info parsing because LLM output is empty")
        return batch, location, time_info, category, json_data
    try:
        json_data = json.loads(output)
    except Exception as e:
        logger.info(f"output:\n{output}")
        logger.info(f"提取关键信息失败: {e}\n尝试从文本中提取 JSON 内容。")

        # 正则表达式匹配 ```json 和 ``` 之间的内容
        pattern = r'```json\s*(.*?)\s*```'  # 捕获内容的正则
        match = re.search(pattern, output, re.DOTALL)  # DOTALL 允许匹配换行符

        if match:
            json_str = match.group(1)  # 提取 JSON 字符串部分
            try:
                json_data = json.loads(json_str)  # 解析 JSON

                logger.info(f"从文本中提取 JSON 内容成功: {json_data}")
            except json.JSONDecodeError as e:
                print("JSON 解析失败:", e)
                logger.exception(f"JSON 解析失败: {e}")
        else:
            logger.exception("未找到 JSON 数据")
            json_data = None

    # 模型偶尔返回 JSON 数组，归一化为首个 dict，避免后续 .get() 报错
    if isinstance(json_data, list):
        json_data = json_data[0] if json_data and isinstance(
            json_data[0], dict) else None

    if json_data:
        try:
            batch = json_data.get("招聘批次", "")
            location = json_data.get("工作地点", "")
            time_info = json_data.get("报名时间", "")
            category = json_data.get("岗位类别", "")
        except Exception as e:
            logger.exception(f"提取招聘关键信息失败: {e}")

    return batch, location, time_info, category, json_data


def get_pdf_files(directory):
    """获取指定目录中的所有PDF文件"""
    pdf_files = []
    try:
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(root, filename))
    except Exception as e:
        logger.exception(f"获取PDF文件失败: {e}")
        return []
    return pdf_files


def filter_pdfs_nowadays(pdf_files):
    """过滤出今天和昨天创建的PDF文件"""
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    return [pdf for pdf in pdf_files if today in pdf or yesterday in pdf]


def filter_pdfs_recruitment(pdf_files, need_delay=False, bot=None):
    """过滤出招聘信息PDF文件"""
    recruitment_pdfs = []
    for pdf in pdf_files:
        logger.info(f"检查是否为招聘信息... ")
        first_text = extract_text_from_first_page(pdf)
        if first_text is None:
            continue
        title, account, publish_date = extract_metadata(first_text)
        if is_article_recruitment(title, bot):
            logger.info(f"找到招聘信息: {pdf}")
            recruitment_pdfs.append(pdf)
        if need_delay:
            time.sleep(random.randint(sleep_time_min, sleep_time_max))
    return recruitment_pdfs


def get_avaliable_pdf_files(directory, RecruimentCheck=False, bot=None, need_delay=False, if_filter_today=True):
    # 1. get all pdf files in the directory
    pdf_files = get_pdf_files(directory)

    # 2. filter out today and yesterday's pdf files
    if if_filter_today:
        pdf_files = filter_pdfs_nowadays(pdf_files)

    # 3. filter out recruitment pdf files
    if RecruimentCheck:
        pdf_files = filter_pdfs_recruitment(
            pdf_files, bot=bot, need_delay=need_delay)

    return pdf_files


def get_pdf_text(pdf_path):
    first_text = extract_text_from_first_page(pdf_path)
    title, account, publish_date = extract_metadata(first_text)
    link = extract_link_after_text(pdf_path)
    full_text = extract_text_from_all_pages(pdf_path)

    # if first_text,link,or full_text is None, return None
    if first_text is None or link is None or full_text is None:
        return None, None, None, None, None

    # 如果全文长度小于ocr_text_len_threshold，则启动OCR
    if len(full_text) < ocr_text_len_threshold:
        # print(f"文本内容过少，启动OCR: {pdf_path}")
        logger.info(f"文本内容过少，启动OCR: {pdf_path}")
        # ocr_text = ocr_pdf(pdf_path) # 使用pytesseract
        try:
            ocr_text = paddle_ocr_pdf(pdf_path)  # 使用paddleocr
            full_text = f"{full_text}\n{ocr_text}"
        except Exception as e:
            logger.exception(f"OCR失败: {e}")
            return None, None, None, None, None

    return title, account, publish_date, link, full_text


class RecruimentArticle():
    def __init__(self, pdf_path):
        self.text = ""
        self.title = ""
        self.account = ""
        self.publish_date = ""
        self.link = ""
        self.summary = ""
        self.batch = ""
        self.location = ""
        self.time_info = ""
        self.category = ""
        self.pdf_path = pdf_path


def get_article_meta_info(pdf_paths):
    """
    从 PDF 路径字典中提取文章元信息并返回文章对象列表。

    :param pdf_paths: 一个字典，格式 {id: path}
    :return: 文章对象的列表
    """
    articles = []
    for article_id, pdf_path in pdf_paths.items():
        # 从 PDF 提取元信息
        title, account, publish_date, link, full_text = get_pdf_text(pdf_path)

        # 如果某些关键元信息缺失，则跳过该文章
        if title is None or account is None or publish_date is None or link is None or full_text is None:
            continue

        # 创建文章对象并填充属性
        article = RecruimentArticle(pdf_path)
        article.original_id = article_id  # 设置 id 属性
        article.text = full_text
        article.title = title
        article.account = account
        article.publish_date = publish_date
        article.link = link
        article.article_type = "general"  # 默认为通用类型

        # 将文章对象添加到结果列表
        articles.append(article)

    return articles


def save_articles_to_db(articles):
    """
    将提取的文章元信息写入数据库表 processed_articles，调用 insert_processed_article 逐条插入。

    :param articles: 一个包含文章对象的列表，每个对象具有以下属性：
                     - id
                     - title
                     - text (全文内容)
                     - publish_date
                     - account
                     - link
                     - pdf_path
    """
    success_count = 0

    for article in articles:
        try:
            # 插入记录，调用 insert_processed_article 函数
            record_id = insert_processed_article(
                original_id=article.original_id,
                title=article.title,
                content=article.text,
                processed_summary=article.summary,
                processed_key_info=article.key_info,
                file_path=article.pdf_path,          # 文件路径
                article_type=article.article_type,
                content_url=article.link,             # 内容链接
                account=article.account,
                publish_date=article.publish_date
            )
            if record_id is not None:
                success_count += 1
                article.id = record_id

            logger.info(f"写入数据库成功: {article.title}")
        except Exception as e:
            logger.exception(f"写入数据库失败: {e}")


def summarize_single_article(article, bot, need_delay=False):
    """Summarize a single article and return the article with its summary"""
    try:
        prompt = prompts_pool.get_prompt(
            task_type="summary", article_type=article.article_type)
        article.summary = summarize_article(
            article.text, bot=bot, summary_prompt=prompt)

        if need_delay:
            time.sleep(random.randint(sleep_time_min, sleep_time_max))

    except Exception as e:
        logger.exception(f"总结文章失败: {e}")
        article.summary = ""

    return article


def batch_update_summaries(articles):
    """Batch update summaries in database after all articles are processed"""
    for article in articles:
        try:
            update_processed_article(
                article.id, article.summary, 'processed_summary')
        except Exception as e:
            logger.exception(
                f"update_processed_article processed_summary failed for article {e}")


def get_article_summary(articles, need_delay=False, bot=None, max_workers=200):
    """Multi-threaded article summarization"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all summarization tasks
        future_to_article = {
            executor.submit(summarize_single_article, article, bot, need_delay): article
            for article in articles
        }

        # Process results as they complete
        for future in future_to_article:
            try:
                article = future.result()
            except Exception as e:
                logger.exception(
                    f"Error processing article summarization: {e}")

    # After all articles are processed, update database in batch
    # batch_update_summaries(articles)


def extract_single_article_key_info(article, bot, need_delay=False):
    """Extract key info for a single article"""
    try:
        prompt = prompts_pool.get_prompt(
            task_type="extract", article_type=article.article_type)
        article.batch, article.location, article.time_info, article.category, article.key_info = extract_key_info(
            article.summary, bot=bot, extract_prompt=prompt)

        if need_delay:
            time.sleep(random.randint(sleep_time_min, sleep_time_max))

    except Exception as e:
        logger.exception(f"提取文章关键信息失败: {e}")
        article.key_info = "None"

    return article


def batch_update_key_info(articles):
    """Batch update key info in database after all articles are processed"""
    for article in articles:
        try:
            update_processed_article(
                article.id, article.key_info, 'processed_key_info')
        except Exception as e:
            logger.exception(
                f"update_processed_article processed_key_info failed  {e}")


def get_article_key_info(articles, need_delay=False, bot=None, max_workers=200):
    """Multi-threaded key info extraction"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all extraction tasks
        future_to_article = {
            executor.submit(extract_single_article_key_info, article, bot, need_delay): article
            for article in articles
        }

        # Process results as they complete
        for future in future_to_article:
            try:
                article = future.result()
            except Exception as e:
                logger.exception(
                    f"Error processing article key info extraction: {e}")

    # After all articles are processed, update database in batch
    # batch_update_key_info(articles)


def _normalize_key_info(key_info):
    """历史数据里 processed_key_info 可能是 JSON 数组，归一化为 dict。"""
    if isinstance(key_info, list):
        key_info = key_info[0] if key_info and isinstance(
            key_info[0], dict) else {}
    elif isinstance(key_info, str):
        try:
            parsed = json.loads(key_info)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
            if isinstance(parsed, dict):
                key_info = parsed
            else:
                key_info = {}
        except Exception:
            key_info = {}
    return key_info or {}


def save_articles_to_csv(articles, output_folder):
    """
    保存所有类型的文章到CSV文件，并动态处理key_info字段。
    :param articles: 文章对象列表
    :param output_folder: 输出文件夹路径
    :return: CSV 和 Excel 文件路径
    """
    # 获取今天的日期
    date_str = datetime.now().strftime('%Y-%m-%d')
    # 初始化 CSV 文件名
    csv_filename = os.path.join(output_folder, f'{date_str}_文章信息汇总.csv')

    # 获取CSV列名：基础列 + 动态提取的key_info字段
    csv_columns = ['标题', '公众号', '发布日期', '原文链接', '摘要']

    # 动态提取所有key_info中的字段（可能会有不同的key值）
    key_info_columns = set()
    for article in articles:
        key_info = _normalize_key_info(article.processed_key_info)
        key_info_columns.update(key_info.keys())

    # 将key_info字段添加到CSV列名
    csv_columns.extend(key_info_columns)

    try:
        with open(csv_filename, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            # 写入列名行
            writer.writerow(csv_columns)

            for article in articles:
                # 提取文章的基本信息
                row = [
                    article.title, article.account, article.publish_date.strftime(
                        '%Y-%m-%d'),
                    article.content_url, article.processed_summary
                ]

                # 提取key_info字段
                key_info = _normalize_key_info(article.processed_key_info)
                # 填充key_info字段到行数据中
                for key in key_info_columns:
                    row.append(key_info.get(key, ""))  # 如果key不存在则填充空值

                # 写入文章数据行
                writer.writerow(row)

    except Exception as e:
        print(f"写入CSV文件失败: {e}")
        return None

    try:
        # 转换CSV文件为Excel
        excel_filename = csv_filename.replace('.csv', '.xlsx')
        csv_to_excel(csv_filename, excel_filename)
    except Exception as e:
        print(f"转换CSV文件到Excel失败: {e}")

    return csv_filename, excel_filename


def save_recruitment_articles_to_csv(articles, output_folder):
    """
    专门保存招聘信息类型的文章到CSV文件。
    :param articles: 招聘类文章对象列表
    :param output_folder: 输出文件夹路径
    :return: CSV 和 Excel 文件路径
    """
    # 获取今天的日期
    date_str = datetime.now().strftime('%Y-%m-%d')
    # 初始化 CSV 文件名
    csv_filename = os.path.join(output_folder, f'{date_str}_招聘信息汇总.csv')
    print(f"csv_filename: {csv_filename}")

    try:
        with open(csv_filename, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            # 写入列名行
            writer.writerow(csv_columns)

            for article in articles:
                try:
                    # 提取文章的基本信息
                    row = [
                        article.title, article.account, article.publish_date.strftime(
                            '%Y-%m-%d'),
                        article.content_url, article.processed_summary
                    ]

                    # 提取招聘专有的key_info字段
                    key_info = _normalize_key_info(article.processed_key_info)
                    category = key_info.get("岗位类别", "")
                    location = key_info.get("工作地点", "")
                    batch = key_info.get("招聘批次", "")
                    time_info = key_info.get("报名时间", "")

                    # 写入招聘信息相关的字段
                    row.extend([batch, location, time_info, category])

                    # 写入文章数据行
                    writer.writerow(row)
                except Exception as e:
                    print(f"{article.title}写入CSV文件失败: {e}")

    except Exception as e:
        print(f"写入CSV文件失败: {e}")
        return None

    try:
        # 转换CSV文件为Excel
        excel_filename = csv_filename.replace('.csv', '.xlsx')
        csv_to_excel(csv_filename, excel_filename)
    except Exception as e:
        print(f"转换CSV文件到Excel失败: {e}")

    return csv_filename, excel_filename


def log_info(articles, start_time):
    current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    end_time = datetime.now()

    logger.info(
        f"【{current_datetime}】共处理 {len(articles)} 篇招聘信息，耗时{(end_time - start_time).seconds/60}分钟")
    logger.info(f"列表如下")
    for article in articles:
        logger.info(article.title)


def get_active_subscription_emails(users_info):
    """Return latest opted-in Pandora subscriber emails from user survey records."""
    latest_users_by_email = {}
    for user in users_info or []:
        email = (getattr(user, "email", "") or "").strip().lower()
        if not email:
            continue
        latest_users_by_email[email] = user

    return [
        email
        for email, user in latest_users_by_email.items()
        if getattr(user, "need_recruiment", False)
    ]


# 使用bot给articles进行分类，使用标题、全文信息的前200字，公众号名称,参考is_article_recruitment()函数
# 4类 'general','recruitment','news','others'  0,1,2,3


def parse_classification_result(classified_result: str):
    """Parse strict class id from model output. Returns one of -1/0/1/2/3 or None."""
    if not classified_result:
        return None
    text = str(classified_result).strip()
    matches = re.findall(r'(?<!\d)(-1|0|1|2|3)(?!\d)', text)
    if not matches:
        return None
    if len(set(matches)) == 1:
        return matches[0]
    return None


def fallback_classify_by_keywords(article):
    """Heuristic fallback when LLM classification output is invalid."""
    text = f"{article.title}\n{article.account}\n{article.text[:500]}".lower()
    if any(k in text for k in ["广告", "vip", "加微信", "进群", "推广"]):
        return "junk"
    if any(k in text for k in ["招聘", "校招", "春招", "秋招", "实习", "网申", "管培", "岗位", "宣讲会", "笔试", "面试", "offer"]):
        return "recruitment"
    if any(k in text for k in ["新闻", "快讯", "发布", "公告", "通知", "会议", "报道", "政策", "消息"]):
        return "news"
    return "general"


def classify_single_article(article, bot, prompts_pool) -> str:
    """Classify a single article and return its category"""
    try:
        def compact(text, limit=180):
            if not text:
                return ""
            return " ".join(str(text).split())[:limit]

        text_for_classification = f"""
        标题: {article.title}
        公众号: {article.account}
        内容前200字: {article.text[:200]}
        """
        prompt = prompts_pool.get_prompt(
            task_type="classify", article_type=article.article_type)
        classified_result = bot.get_response(
            prompt, text_for_classification, show_log=True)
        class_id = parse_classification_result(classified_result)
        final_result = classified_result
        result_source = "primary"

        # Retry once with stricter prompt when output is invalid.
        if class_id is None:
            retry_prompt = (
                "你是文章分类器。请仅返回一个编号（-1/0/1/2/3），不要解释。\n"
                "-1=垃圾, 0=通用, 1=招聘, 2=新闻, 3=其他。"
            )
            retry_input = f"待分类文本：\n{text_for_classification}\n\n仅返回一个编号。"
            retry_result = bot.get_response(
                retry_prompt, retry_input, show_log=True)
            class_id = parse_classification_result(retry_result)
            final_result = retry_result
            result_source = "retry"

            if class_id is None:
                category = fallback_classify_by_keywords(article)
                logger.warning(
                    f"分类返回无效，使用关键词兜底分类: title={article.title[:80]}, "
                    f"primary={compact(classified_result)}, retry={compact(retry_result)}, category={category}")
                return article, category

        id_to_category = {
            "-1": "junk",
            "0": "general",
            "1": "recruitment",
            "2": "news",
            "3": "others",
        }
        category = id_to_category.get(class_id, "general")

        # If model says general but strong recruitment keywords exist, force correction.
        if category == "general":
            keyword_category = fallback_classify_by_keywords(article)
            if keyword_category == "recruitment":
                logger.info(
                    f"分类纠偏: title={article.title[:80]}, model=general({result_source}), keyword=recruitment")
                category = "recruitment"

        result_for_log = compact(final_result)
        if class_id == "-1":
            logger.info(
                f"分类结果: {result_for_log}, source={result_source}, 分类为垃圾")
            return article, category

        if class_id == "1":
            logger.info(
                f"分类结果: {result_for_log}, source={result_source}, 分类为招聘信息")
        elif class_id == "2":
            logger.info(
                f"分类结果: {result_for_log}, source={result_source}, 分类为新闻")
        elif class_id == "3":
            logger.info(
                f"分类结果: {result_for_log}, source={result_source}, 分类为其他")
        else:
            if category == "recruitment":
                logger.info(
                    f"分类结果: {result_for_log}, source={result_source}, 分类为招聘信息")
            else:
                logger.info(
                    f"分类结果: {result_for_log}, source={result_source}, 分类为通用")

    except Exception as e:
        logger.exception(f"分类文章失败: {e}, default to general")
        category = "general"

    return article, category


def classify_articles(articles: List, bot=None, max_workers=200):
    """Multi-threaded article classification"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all classification tasks
        future_to_article = {
            executor.submit(classify_single_article, article, bot, prompts_pool): article
            for article in articles
        }

        # Process results as they complete
        for future in future_to_article:
            try:
                article, category = future.result()
                article.article_type = category

                # Update database immediately after classification
                # try:
                #     update_processed_article(
                #         article.id, article.article_type, 'article_type')
                # except Exception as e:
                #     logger.exception(
                #         f"update_processed_article processed_category failed: {e}")

            except Exception as e:
                logger.exception(
                    f"Error processing article classification: {e}")


def ocr_pdf(pdf_path, method="ppocr"):
    try:
        if method == "ppocr":
            return paddle_ocr_pdf(pdf_path)
        elif method == "gemini":
            return gemini_ocr_pdf(pdf_path)  # 使用paddleocr
        else:
            raise (f"请使用有效的ocr方法，输入的为{method}")
    except Exception as e:
        logger.exception(f"{method} OCR失败: {e},返回空字符串")
        return ""


def get_article_meta_info_from_db(db_articles):
    """直接从数据库记录生成文章对象"""
    articles = []
    for record in db_articles:
        article = RecruimentArticle(pdf_path=record['pdf_path'])
        article.original_id = record['id']
        article.text = record.get('content') or ""
        if len(article.text) < ocr_text_len_threshold:
            logger.info(
                f"文本字数：{len(article.text)} 过少，启动OCR: {article.pdf_path}")
            ocr_text = ocr_pdf(article.pdf_path, method="ppocr")
            article.text = f"{article.text} \n\n 以下是OCR的结果：{ocr_text}"

        article.title = record['title']
        article.account = record['account']
        article.publish_date = record['publish_date']
        article.link = record['url']
        article.article_type = "general"
        articles.append(article)
    return articles


def filter_junk_articles(articles):
    """
    过滤掉垃圾文章
    """
    JUNK_KEYWORDS = ["广告", "vip", "加微信", "进群", "推广"]
    filtered_articles = []

    for article in articles:
        summary_text = article.summary or ""
        is_junk = any(keyword in summary_text for keyword in JUNK_KEYWORDS)
        if is_junk:
            article.article_type = "junk"
            logger.info(f"检测到垃圾文章: {article.title}")

        if article.article_type != "junk":
            filtered_articles.append(article)

    return filtered_articles


def process(directory, output_folder, RecruimentCheck=False, Get_Summary=True, Get_key_info=True, need_delay=False, if_upload=True, if_filter_today=True, config=None, record_limit=None, max_workers=200):
    """
    Parameters:
    directory (str): The directory where the PDF files are located.
    output_folder (str): The directory where the output Excel file will be saved.
    """
    if config is None:
        logger.error("config.json not provided. Exiting...")
        return

    llm = config.get("llm")
    if llm is None:
        logger.error("llm not provided. Exiting...")
        return
    if llm == "openai":
        api_key = config.get("openai_api_key")
        base_url = config.get("openai_base_url")
        model = config.get("model")
        bot = OpenaiBot(api_key, base_url, model)
    elif llm == "deepseek":
        api_key = config.get("deepseek_api_key") or config.get("openai_api_key")
        base_url = config.get("deepseek_base_url") or config.get("openai_base_url") or "https://api.deepseek.com"
        model = config.get("model")
        bot = OpenaiBot(api_key, base_url, model)
    # elif llm == "zhipu":
    #     api_key = config.get("zhipu_api_key")
    #     model = config.get("model")
    #     bot = ZhipuBot(api_key, model)
    else:
        logger.error(f"Unsupported llm={llm}. Supported llms: {llm_model_list}")
        return

    start_time = datetime.now()
    # 1. get to be processed pdf files
    # pdf_files = get_avaliable_pdf_files(
    #     directory, RecruimentCheck, bot=bot, need_delay=need_delay, if_filter_today=if_filter_today)

    #  1. get to be processed pdf files from db
    # pdf_files = get_today_and_yesterday_file_paths(directory)
    # 默认处理"昨天"；补跑/测试时可用环境变量指定日期范围
    start_date = os.getenv("PDFSUMMARY_START_DATE") or (
        datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    end_date = os.getenv("PDFSUMMARY_END_DATE") or start_date
    # 三天前
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    db_articles = fetch_unprocessed_articles(
        start_date=start_date, end_date=end_date)  # 默认处理"昨天"

    # record_limit = 10
    if record_limit:
        db_articles = db_articles[:record_limit]
    # if record_limit:
    #     pdf_files = dict(islice(pdf_files.items(), record_limit))
    # print len of pdf_files,and other info
    logger.info(f"articles sum: {len(db_articles)}")

    if len(db_articles) == 0:
        logger.info("没有找到昨天的招聘信息")
        return

    # 2. get meta info
    try:
        articles = get_article_meta_info_from_db(db_articles)  # 修改后的元数据获取
    except Exception as e:
        logger.exception(f"获取文章的元信息失败: {e}")
        return

    # 2.1 get arricle category
    classify_articles(articles, bot=bot, max_workers=max_workers)

    # 2.2 filter out junk articles
    articles = filter_junk_articles(articles)
    logger.info(f"过滤掉垃圾文章后，剩余文章数: {len(articles)}")

    # 3. get summary with llm
    if Get_Summary:
        get_article_summary(articles, bot=bot,
                            need_delay=need_delay, max_workers=max_workers)

    # 3.1 step 2 filter out junk articles again
    articles = filter_junk_articles(articles)
    logger.info(f"过滤掉垃圾文章后，剩余文章数: {len(articles)}")

    # 3.2. get key info with llm
    if Get_key_info:
        get_article_key_info(
            articles, bot=bot, need_delay=need_delay, max_workers=max_workers)

    # 4 save to db
    save_articles_to_db(articles)

    # 5. fetch today's articles list from db
    recruitment_articles = fetch_processed_articles_by_type(
        'recruitment', only_today=True)
    fetch_articles_by_type
    if record_limit:
        recruitment_articles = recruitment_articles[:record_limit]

    # 5.5 save to csv
    csv_file, excel_filename = save_recruitment_articles_to_csv(
        recruitment_articles, output_folder)

    # 6. 上传
    if if_upload:
        try:
            # upload_to_airtable(csv_file, config)
            upload_recruitment_table(csv_file, config=config)
        except Exception as e:
            logger.exception(f"上传失败: {e}")

    # 7 send personal email and update rss xml
    users_info = fetch_user_info_and_update_database(config)
    try:
        email_list = get_active_subscription_emails(users_info)

        for email in email_list:
            try:
                articles = get_user_subscribed_accounts_processed_articles(
                    email, only_today=True)

                # if articles is empty, skip
                if len(articles) == 0:
                    logger.info(f"没有找到{email}的订阅文章")
                    continue

                personal_email_content = construct_personal_email_content(
                    articles)
                # subject = "9月13日 微秘Daily"
                subject = f"{datetime.now().strftime('%m月%d日')} 微秘Daily"
                send_email(subject, personal_email_content,
                           email, text_type="html")

                # update rss xml # 11.24 暂时不需要了
                # gen_and_update_xml(email=email, articles=articles)
                logger.info(f"发送邮件成功: {email}, 邮件主题: {subject}")
            except Exception as e:
                logger.exception(f"发送邮件失败: {e}, email: {email}")

    except Exception as e:
        logger.exception(f"发送邮件失败: {e}")

    # 8. log info
    log_info(articles, start_time)


def main(pdf_directory, output_folder_path, config):
    """
    The main function that processes PDFs and saves the results to an Excel file.
    :param pdf_directory: str, the path to the directory containing PDF files.
    :param output_folder_path: str, the path to the directory where the result should be saved.
    """
    # Ensure the output folder exists
    if not os.path.exists(output_folder_path):
        os.makedirs(output_folder_path)

    # Process the PDF files and save the results to an Excel file
    RecruimentCheck = True
    Get_Summary = True
    Get_key_info = True
    Need_Delay = False
    if_upload = True
    if_filter_today = True
    max_workers = config.get("max_workers", 200)
    record_limit = None

    # Optional runtime throttle for faster end-to-end validation.
    record_limit_env = os.getenv("PDFSUMMARY_RECORD_LIMIT", "").strip()
    if record_limit_env:
        try:
            parsed_limit = int(record_limit_env)
            if parsed_limit > 0:
                record_limit = parsed_limit
                logger.info(
                    f"Use record_limit from env PDFSUMMARY_RECORD_LIMIT={record_limit}")
            else:
                logger.warning(
                    f"Ignore non-positive PDFSUMMARY_RECORD_LIMIT={record_limit_env}")
        except ValueError:
            logger.warning(
                f"Ignore invalid PDFSUMMARY_RECORD_LIMIT={record_limit_env}")

    max_workers_env = os.getenv("PDFSUMMARY_MAX_WORKERS", "").strip()
    if max_workers_env:
        try:
            max_workers = int(max_workers_env)
        except ValueError:
            logger.warning(
                f"Ignore invalid PDFSUMMARY_MAX_WORKERS={max_workers_env}")

    try:
        max_workers = int(max_workers)
    except (TypeError, ValueError):
        logger.warning(f"Invalid max_workers={max_workers}, fallback to 200")
        max_workers = 200

    if max_workers < 1:
        logger.warning(f"max_workers={max_workers} is < 1, fallback to 1")
        max_workers = 1

    logger.info(f"Use max_workers={max_workers}, need_delay={Need_Delay}")

    process(directory=pdf_directory, output_folder=output_folder_path,
            RecruimentCheck=RecruimentCheck, Get_Summary=Get_Summary,
            Get_key_info=Get_key_info, need_delay=Need_Delay,
            if_upload=if_upload, if_filter_today=if_filter_today,  config=config, max_workers=max_workers, record_limit=record_limit)


# unit test,写一个函数，测试test_mode下的文件夹路径，跑一遍完整的流程，但是不上传到airtable和飞书.没有参数，直接运行
def test_process():
    pdf_directory = r"D:\yy\wechatmonitor\output\airtleSave"
    output_folder_path = os.path.join(PROJECT_ROOT, "data")
    config_path = os.getenv(
        "PDFSUMMARY_CONFIG", os.path.join(PROJECT_ROOT, "config.json"))

    config = read_config(config_path)

    RecruimentCheck = True
    Get_Summary = True
    Get_key_info = True
    Need_Delay = True
    if_upload = False
    if_filter_today = False
    record_limit = 2

    process(directory=pdf_directory, output_folder=output_folder_path,
            RecruimentCheck=RecruimentCheck, Get_Summary=Get_Summary,
            Get_key_info=Get_key_info, need_delay=Need_Delay,
            if_upload=if_upload, if_filter_today=if_filter_today,  config=config, record_limit=record_limit)


if __name__ == "__main__":
    test_mode = False
    if test_mode:
        pdf_directory = r"D:\yy\wechatmonitor\output\testaritle"
        output_folder_path = os.path.join(PROJECT_ROOT, "data")
    else:
        pdf_directory = r"D:\yy\wechatmonitor\output\airtleSave"
        output_folder_path = os.path.join(PROJECT_ROOT, "data")
    config_path = os.getenv(
        "PDFSUMMARY_CONFIG", os.path.join(PROJECT_ROOT, "config.json"))

    # Check if sufficient arguments were passed to the script
    if len(sys.argv) < 4:
        pdf_directory_arg = pdf_directory
        output_folder_path_arg = output_folder_path
        config_path_arg = config_path
    else:
        # Get the PDF directory and output folder path from command line arguments
        pdf_directory_arg = sys.argv[1]
        output_folder_path_arg = sys.argv[2]
        config_path_arg = sys.argv[3]

    # Run the main function
    try:
        config = read_config(config_path)
        main(pdf_directory_arg, output_folder_path_arg, config)
    except Exception as e:
        logger.exception(
            "An error occurred while processing the PDF files. Exiting...")
        sys.exit(1)
