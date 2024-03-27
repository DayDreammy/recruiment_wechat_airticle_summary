import csv
import time
import requests
import json

import logging

logger = logging.getLogger()


def upload_csv_to_airtable(tokens, base_id, table_name, csv_file_path, batch_size=10):
    # 设置 API URL
    airtable_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"

    # 设置请求头
    headers = {
        'Authorization': f'Bearer {tokens}',
        'Content-Type': 'application/json',
    }

    # 函数，用于发送数据到 Airtable
    def create_records(records):
        data = json.dumps({"records": records})
        response = requests.post(
            airtable_url,
            headers=headers,
            data=json.dumps({
                "records": records,  # 将 records 列表转换为 JSON 字符串
                "typecast": True  # 加入typecast参数
            })
        )
        if response.status_code == 200:
            logger.info("Records created successfully: %s", response.json())
            print("Records created successfully:", response.json())
        else:
            logger.error("Failed to create records: %s", response.text)
            print("Failed to create records:", response.text)

    # 准备批量发送的数据
    batch_records = []

    # 读取 CSV 文件并准备数据
    with open(csv_file_path, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            batch_records.append({"fields": row})
            if len(batch_records) == batch_size:
                create_records(batch_records)  # 创建记录
                batch_records = []  # 清空批量列表，准备下一批次的数据
                # 延时 1 秒，避免 API 调用频率过高
                time.sleep(1)

    # 发送剩余的记录（如果有）
    if batch_records:
        create_records(batch_records)

    print("All records are created.")


def upload_to_airtable(csv_file_path, config=None):
    if config is not None:
        tokens = config.get('airtable_tokens')
        base_id = config.get('airtable_baseid')
        table_name = config.get('airtable_table_name')
        # check if the config is valid
        if tokens is None or base_id is None or table_name is None:
            logger.error("Invalid config provided")
            return
    else:
        logger.error("No config provided")
        return
    try:
        upload_csv_to_airtable(tokens, base_id, table_name, csv_file_path)
    except Exception as e:
        logger.exception("Failed to upload to Airtable.")
        logger.exception(e)


if __name__ == '__main__':
    upload_csv_to_airtable(
        r'E:\wechatmonitor\public\2023-12-26_招聘信息汇总.csv')
