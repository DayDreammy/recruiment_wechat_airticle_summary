import os
import csv
import requests
import time
from datetime import datetime
from common import csv_columns

import logging

logger = logging.getLogger()


def get_feishu_table_metadata(tenant_access_token, app_token):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
    headers = {
        "Authorization": f"Bearer {tenant_access_token}"
    }
    response = requests.get(url, headers=headers)
    return response.json()


def list_records_in_feishu_table(tenant_access_token, app_token, table_id, page_size=20):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{
        app_token}/tables/{table_id}/records?page_size={page_size}"
    headers = {
        "Authorization": f"Bearer {tenant_access_token}"
    }
    response = requests.get(url, headers=headers)
    return response.json()


def get_tenant_access_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        token_response = response.json()
    else:
        return None

    if token_response and token_response.get('code') == 0:
        tenant_access_token = token_response.get('tenant_access_token')
        print("Tenant Access Token:", tenant_access_token)
        return tenant_access_token
    else:
        print("Error obtaining token:", token_response)
        return None

# 将日期字符串转换为 UNIX 时间戳（毫秒）


def date_to_timestamp(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")  # 确保这个格式与你的 CSV 中的日期格式一致
    timestamp = int(dt.timestamp() * 1000)  # 将日期转换为 UNIX 时间戳（毫秒）
    return timestamp


def construct_record(records):

    records_data = []
    for record in records:
        # 构造超链接字段
        record = record['fields']
        hyperlink = {
            "text": record.get(csv_columns[0]),
            "link": record.get(csv_columns[3])
        }

        # 转换发布日期
        try:
            record['发布日期'] = date_to_timestamp(record.get(csv_columns[2]))
        except:
            print("Error converting date:", record['发布日期'])
            logger.error("Error converting date:", record['发布日期'])
            continue

        # 构造请求体
        data = {
            "fields": {
                "标题": hyperlink,  # 标题字段现在是超链接格式
                "公众号": record.get(csv_columns[1]),  # 公众号字段是文本格式
                "发布日期": record.get(csv_columns[2]),  # 发布日期字段是日期格式
                "摘要": record.get(csv_columns[4]),  # 摘要字段是文本格式
                "招聘批次": record.get(csv_columns[5]),  # 招聘批次字段是文本格式
                "地点": record.get(csv_columns[6]),  # 地点字段是文本格式
                "时间": record.get(csv_columns[7]),  # 时间字段是文本格式
                "标签": record.get(csv_columns[8])  # 岗位标签字段是文本格式
            }
        }

        records_data.append(data)

    return records_data


def post_record(record, feishu_url, headers):
    # 发送 POST 请求
    response = requests.post(feishu_url, headers=headers, json=record)
    if response.status_code == 200:
        response_data = response.json()
        # 处理并打印记录的详细信息
        if response_data['code'] == 0:  # 成功
            print("Record added successfully:", response_data)
        else:
            print("Error:", response_data['msg'])
    else:
        print("Failed to add record:", response.text)
    time.sleep(0.1)  # 延时以避免超过 API 调用频率


def post_record_loop(records, feishu_url, headers):
    records = construct_record(records)
    for record in records:
        post_record(record, feishu_url, headers)


def post_record_batch(records, feishu_url, headers):
    records = construct_record(records)
    data = {"records": records}

    url = feishu_url + "/batch_create"
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        response_data = response.json()
        if response_data['code'] == 0:  # 成功
            logger.info("Records added successfully:", response_data)
            print("Records added successfully:", response_data)
        else:
            logger.error("Error:", response_data['msg'])
            print("Error:", response_data['msg'])
    else:
        logger.error("Failed to add records:", response.text)
        print("Failed to add records:", response.text)


def delete_existing_records(records, titles_today=None):
    if titles_today is None:
        titles_today = []
    records_new = []
    for record in records:
        title = record['fields']['原文链接']
        if title in titles_today:
            continue
        records_new.append(record)
    return records_new


def query_records_title(feishu_url, headers, only_today=False):
    # 构建请求URL
    url = feishu_url+"/search"
    filed_name = "标题"
    data = {
        "field_names": [
            filed_name
        ],
    }
    if only_today:
        filter_name = "发布日期"
        data["filter"] = {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": filter_name,
                    "operator": "is",
                    "value": ["Today", ""]
                }
            ]
        }

    titles = []
    idx = 0
    while True:

        # 发送POST请求
        page_token = ''
        url_p = url
        if page_token:
            url_p = url + f"?page_token={page_token}"
        response = requests.post(url_p, headers=headers, json=data)

        # 检查响应
        if response.status_code == 200:
            result = response.json()  # 返回响应的JSON数据
        else:
            return response.text  # 出错时返回错误信息

        if result and result.get('code') == 0:
            total_len = result.get('data').get('total')
            items = result.get('data').get('items')
            for item in items:
                titles.append(item.get('fields').get(filed_name).get('link'))
                idx += 1
                if idx >= total_len:
                    return titles
            if result.get('data').get('has_more'):
                page_token = result.get('data').get('page_token')
            else:
                break
        else:
            return response.json()

    return titles

# 优化后的 create_records 函数


def create_records(records, feishu_url, headers, titles_today=None):
    if titles_today is None:
        titles_today = []
    # delete existing records
    records = delete_existing_records(records, titles_today)
    if len(records) == 0:
        print("No new records to add.")
        return

    # post_record_loop(records, feishu_url, headers)
    post_record_batch(records, feishu_url, headers)


def upload_to_feishu(csv_file_path, batch_size=500, config=None):
    if config is not None:
        app_id = config.get('feishu_appid')
        app_secret = config.get('feishu_appsecret')
        app_token = config.get('feishu_apptoken')
        table_id = config.get('feishu_table_id')
        # check if the config is valid
        if app_id is None or app_secret is None or app_token is None or table_id is None:
            logger.error("Invalid config provided")
            return
    else:
        logger.error("No config provided")
        return

    tenant_access_token = get_tenant_access_token(app_id, app_secret)

    # 设置 API URL
    feishu_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{
        app_token}/tables/{table_id}/records"

    # 设置请求头
    headers = {
        'Authorization': f'Bearer {tenant_access_token}',
        'Content-Type': 'application/json',
    }

    # 获取已经存在的记录标题
    titles_today = query_records_title(feishu_url, headers, only_today=True)

    # 准备批量发送的数据
    batch_records = []

    # 读取 CSV 文件并准备数据
    with open(csv_file_path, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            batch_records.append({"fields": row})
            if len(batch_records) == batch_size:
                create_records(batch_records, feishu_url,
                               headers, titles_today)
                batch_records = []  # 清空批量列表，准备下一批次的数据
                time.sleep(0.1)

    # 发送剩余的记录（如果有）
    if batch_records:
        create_records(batch_records, feishu_url, headers, titles_today)

    print("All records are uploaded. to feishu")


def find_csv_filenames(path_to_dir, suffix=".csv"):
    filenames = os.listdir(path_to_dir)
    return [filename for filename in filenames if filename.endswith(suffix)]


def main():
    csv_file_path = r"D:\yy\wechatmonitor\public\2024-03-07_招聘信息汇总.csv"
    upload_to_feishu(csv_file_path)


if __name__ == '__main__':
    main()
