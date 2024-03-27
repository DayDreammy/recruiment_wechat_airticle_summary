import os
import random
import sys
import io
import re
import csv
import json
from datetime import datetime, timedelta
import time
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import logging
import os
from datetime import datetime


from bot import OpenaiBot, ZhipuBot
from common import csv_columns
from prompts import Prompts
from up2feishu import upload_to_feishu
from csv2excel import csv_to_excel
from up2airtable import upload_to_airtable


# create logs folder if not exists
log_dir = r"D:\yy\wechatmonitor\code\logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# use current date as log file name
current_date = datetime.now().strftime('%Y-%m-%d')
log_file_name = f'{current_date}.log'
log_file_path = os.path.join(log_dir, log_file_name)

# logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()  # 同时输出日志到标准输出，可以去掉如果不需要
    ]
)
logger = logging.getLogger()


# 设置pytesseract的Tesseract命令路径
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


prompts = Prompts()
summary_prompt = prompts.summary_prompt
judge_prompt = prompts.judge_prompt
extract_prompt = prompts.extract_prompt
# Define your thresholds here
ocr_text_len_threshold = 1100
max_gpt_input_len = 3000
max_gpt_output_tokens = 700
sleep_time_min = 3  # seconds
sleep_time_max = 7  # seconds

# supported llm, other llms suggest to use oneapi etc.
llm_model_list = ["openai", "zhipu"]


###
# pdf functions
###
def extract_text_from_first_page(pdf_path):
    with fitz.open(pdf_path) as pdf:
        # 提取第一页的文本
        text = pdf[0].get_text()
    return text


def extract_text_from_all_pages(pdf_path):
    with fitz.open(pdf_path) as pdf:
        # 提取所有页面的文本
        text = ""
        for page in pdf:
            text += page.get_text()
    return text


def extract_link_after_text(pdf_path, search_text="原文地址"):
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


def extract_metadata(text):
    title_pattern = r'原文地址：(.*?)\n'
    account_pattern = r'公号:(.*?)\s'
    time_pattern = r'发布时间:(\d{4}-\d{2}-\d{2})'

    title = re.search(title_pattern, text).group(
        1) if re.search(title_pattern, text) else ""
    account = re.search(account_pattern, text).group(
        1) if re.search(account_pattern, text) else ""
    publish_date = re.search(time_pattern, text).group(
        1) if re.search(time_pattern, text) else ""

    return title, account, publish_date


def ocr_pdf(pdf_path):
    # 打开PDF文件
    pdf = fitz.open(pdf_path)

    # 创建一个空的列表来存储每一页的文本
    ocr_texts = []

    for page_num in range(len(pdf)):
        # 获取PDF的一页
        page = pdf[page_num]

        # # # ocr完乱七八糟的字符太多了，简直是浪费token,这里只ocr前2页，后面会改成提取图片作为附件上传。
        # 0307update:经测试，50篇文章，字数多了60%，但是ocr效果不好，所以还是ocr前2页
        if page_num > 1:
            break

        # 将PDF页面转换为图像
        pix = page.get_pixmap()
        img_data = pix.tobytes("ppm")
        image = Image.open(io.BytesIO(img_data))

        # 使用pytesseract进行OCR
        text = pytesseract.image_to_string(
            image, lang='chi_sim', config='--tessdata-dir "C:\\Program Files\\Tesseract-OCR\\tessdata"')  # 简体中文+英文

        # 添加识别的文本到列表中
        ocr_texts.append(text)

    # 关闭PDF文件
    pdf.close()

    # 将所有页面的文本连接成一个长字符串
    ocr_text_all = "\n".join(ocr_texts)

    # 返回所有页面的OCR文本
    return ocr_text_all


def split_text(text, max_length=max_gpt_input_len):
    """将文本分割成不超过max_length的多个部分"""
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]


def is_article_recruitment(text, bot=None):
    """判断文本是否是招聘信息"""
    judge = "0"
    if bot is None:
        return True

    judge = bot.get_response(judge_prompt, text)

    if judge == "1":
        return True
    else:
        return False


def summarize_article(text, bot=None):
    """
    Summarizes the given text.

    This function first splits the text into several parts, then summarizes each part. All the summaries are combined into a new text.
    If the original text is split into several parts, the combined summary is summarized again.

    If the length of the combined summary exceeds the input length limit of GPT, only the first max_gpt_input_len characters are summarized.

    Args:
        text (str): The text to be summarized.

    Returns:
        str: The summary of the text.
    """
    # 检查文本长度并分割
    parts = split_text(text)

    # 为每个部分生成总结
    summaries = [bot.get_response(summary_prompt, part) for part in parts]

    # 将所有总结整合为一个新的文本
    integrated_summary = ' '.join(summaries)
    final_summary = integrated_summary

    # 如果有超过1个part，则再次总结
    if len(parts) > 1:
        # 如果文本长度超过阈值，则只取前threshold个字符
        if len(integrated_summary) > max_gpt_input_len:
            integrated_summary = integrated_summary[:max_gpt_input_len]
        # final_summary=summarize_part_openai(integrated_summary)
        final_summary = bot.get_response(summary_prompt, integrated_summary)

    if final_summary != '':
        end_line = f"\n\n(Powered by {bot.model}, 请以原文为准。)"
        final_summary += end_line

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


def extract_key_info(text, bot=None):
    batch = ""
    location = ""
    time_info = ""
    category = ""

    if bot is None:
        return batch, location, time_info, category

    output = bot.get_response(extract_prompt, text)
    try:
        json_data = json.loads(output)
    except Exception as e:
        logger.exception(f"提取关键信息失败: {e}\n尝试从文本中提取 JSON 内容。")
        json_regex = r'{[^}]*}'
        match = re.search(json_regex, output)
        if match:
            match_data = match.group(0)
            json_data = json.loads(match_data)
            print("找到的 JSON 内容是:")
            print(json_data)
        else:
            print("没有找到 JSON 内容。")
            json_data = None

    if json_data:
        try:
            batch = json_data.get("招聘批次", "")
            location = json_data.get("工作地点", "")
            time_info = json_data.get("报名时间", "")
            category = json_data.get("岗位类别", "")
        except Exception as e:
            logger.exception(f"提取关键信息失败: {e}")

    return batch, location, time_info, category


def get_pdf_files(directory):
    """获取指定目录中的所有PDF文件"""
    pdf_files = []
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, filename))
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
        logger.info(f"检查是否为招聘信息... {pdf}")
        first_text = extract_text_from_first_page(pdf)
        title, account, publish_date = extract_metadata(first_text)
        if is_article_recruitment(title, bot):
            recruitment_pdfs.append(pdf)
        if need_delay:
            time.sleep(random.randint(sleep_time_min, sleep_time_max))
    return recruitment_pdfs


def get_avaliable_pdf_files(directory, RecruimentCheck=False, bot=None):
    # 1. get all pdf files in the directory
    pdf_files = get_pdf_files(directory)

    # 2. filter out today and yesterday's pdf files
    pdf_files = filter_pdfs_nowadays(pdf_files)

    # 3. filter out recruitment pdf files
    if RecruimentCheck:
        pdf_files = filter_pdfs_recruitment(pdf_files, bot=bot)

    return pdf_files


def get_pdf_text(pdf_path):
    first_text = extract_text_from_first_page(pdf_path)
    title, account, publish_date = extract_metadata(first_text)
    link = extract_link_after_text(pdf_path)
    full_text = extract_text_from_all_pages(pdf_path)

    # 如果全文长度小于ocr_text_len_threshold，则启动OCR
    if len(full_text) < ocr_text_len_threshold:
        print(f"文本内容过少，启动OCR: {pdf_path}")
        ocr_text = ocr_pdf(pdf_path)
        full_text = ocr_text + full_text

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
    articles = []
    for pdf_path in pdf_paths:
        title, account, publish_date, link, full_text = get_pdf_text(pdf_path)
        article = RecruimentArticle(pdf_path)
        article.text = full_text
        article.title = title
        article.account = account
        article.publish_date = publish_date
        article.link = link
        articles.append(article)
    return articles


def get_article_summary(articles, need_delay=False, bot=None):
    for article in articles:
        try:
            article.summary = summarize_article(article.text, bot=bot)
            if need_delay:
                time.sleep(random.randint(sleep_time_min, sleep_time_max))
        except Exception as e:
            logger.exception(f"总结文章失败: {e}")
            article.summary = ""


def get_article_key_info(articles, need_delay=False, bot=None):
    for article in articles:
        article.batch, article.location, article.time_info, article.category = extract_key_info(
            article.summary, bot=bot)
        if need_delay:
            time.sleep(random.randint(sleep_time_min, sleep_time_max))


def save_articles_to_csv(articles, output_folder):
    # Get yesterday's date formatted as yyyy-mm-dd
    date_str = datetime.now().strftime('%Y-%m-%d')
    # Build CSV filename including folder path
    csv_filename = os.path.join(output_folder, f'{date_str}_招聘信息汇总.csv')

    try:
        with open(csv_filename, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            # 写入标题行
            writer.writerow(csv_columns)

            for article in articles:
                writer.writerow([article.title, article.account, article.publish_date, article.link,
                                article.summary, article.batch, article.location, article.time_info, article.category])
    except Exception as e:
        logger.exception(f"写入CSV文件失败: {e}")
        return None

    try:
        # Convert CSV to Excel
        csv_to_excel(csv_filename, csv_filename.replace('.csv', '.xlsx'))
    except Exception as e:
        logger.exception(f"转换CSV文件到Excel失败: {e}")

    return csv_filename


def log_info(articles, start_time):
    current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    end_time = datetime.now()

    logger.info(f"【{current_datetime}】共处理 {len(articles)} 篇招聘信息，耗时{
                (end_time - start_time).seconds/60}分钟")
    logger.info(f"列表如下")
    for article in articles:
        logger.info(article.title)


def process(directory, output_folder, RecruimentCheck=False, Get_Summary=True, Get_key_info=True, config=None):
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
    elif llm == "zhipu":
        api_key = config.get("zhipu_api_key")
        model = config.get("model")
        bot = ZhipuBot(api_key, model)

    start_time = datetime.now()
    # 1. get to be processed pdf files
    pdf_files = get_avaliable_pdf_files(directory, RecruimentCheck, bot=bot)
    if len(pdf_files) == 0:
        logger.info("没有找到今天和昨天的招聘信息PDF文件")
        return

    # 2. get meta info
    try:
        articles = get_article_meta_info(pdf_files)
    except Exception as e:
        logger.exception(f"获取文章的元信息失败: {e}")
        return

    # 3. get summary with llm
    if Get_Summary:
        get_article_summary(articles, bot=bot)

    # 4. get key info with llm
    if Get_key_info:
        get_article_key_info(articles, bot=bot)

    # 5. save to csv
    csv_file = save_articles_to_csv(articles, output_folder)

    # 6. 上传
    if csv_file:
        try:
            upload_to_airtable(csv_file, config)
            upload_to_feishu(csv_file, config=config)
        except Exception as e:
            logger.exception(f"上传失败: {e}")

    # 7. log info
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
    process(pdf_directory, output_folder_path,
            RecruimentCheck, Get_Summary, Get_key_info, config)


def read_config(config_path):
    try:
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
            return config
    except FileNotFoundError:
        print(f"Error: The file {config_path} was not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: The file {config_path} could not be parsed.")
        return None


if __name__ == "__main__":
    test_mode = True
    if test_mode:
        pdf_directory = r"D:\yy\wechatmonitor\output\testaritle"
        output_folder_path = r"D:\yy\wechatmonitor\public\test"
    else:
        pdf_directory = r"D:\yy\wechatmonitor\output\airtleSave"
        output_folder_path = r"D:\yy\wechatmonitor\public"
    config_path = r"D:\yy\wechatmonitor\code\config.json"

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
