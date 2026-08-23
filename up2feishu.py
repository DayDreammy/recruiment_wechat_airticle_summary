import csv
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from common import csv_columns
from sqldb import process_user_batch

logger = logging.getLogger("pdfsummary")

FEISHU_OPEN_API = "https://open.feishu.cn/open-apis"
FEISHU_BATCH_SIZE = 500


def _require_config(config):
    if config is None:
        raise ValueError("config is required")
    return config


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_batch_size(config, default=FEISHU_BATCH_SIZE):
    if not config:
        return default
    try:
        value = int(config.get("feishu_batch_size", default))
    except (TypeError, ValueError):
        return default
    return min(max(value, 1), FEISHU_BATCH_SIZE)


def _get_main_table_config(config):
    config = _require_config(config)
    app_id = config.get("feishu_appid")
    app_secret = config.get("feishu_appsecret")
    app_token = config.get("feishu_apptoken")
    table_id = config.get("feishu_table_id")
    if not all([app_id, app_secret, app_token, table_id]):
        raise ValueError("Missing Feishu main table config")
    return app_id, app_secret, app_token, table_id


def _get_user_table_config(config):
    config = _require_config(config)
    app_id = config.get("feishu_appid")
    app_secret = config.get("feishu_appsecret")
    app_token = config.get("feishu_email_list_apptoken")
    table_id = config.get("feishu_email_list_table_id")
    if not all([app_id, app_secret, app_token, table_id]):
        raise ValueError("Missing Feishu user table config")
    return app_id, app_secret, app_token, table_id


def _build_headers(tenant_access_token):
    return {
        "Authorization": f"Bearer {tenant_access_token}",
        "Content-Type": "application/json",
    }


def _feishu_url(app_token, table_id):
    return f"{FEISHU_OPEN_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records"


def _request_json(method, url, headers=None, payload=None, timeout=60):
    response = requests.request(method, url, headers=headers, json=payload, timeout=timeout)
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Feishu API returned non-JSON response, status={response.status_code}, body={response.text[:500]}"
        ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Feishu API HTTP {response.status_code}: {json.dumps(data, ensure_ascii=False)}"
        )
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu API error: {json.dumps(data, ensure_ascii=False)}")
    return data


def get_feishu_table_metadata(tenant_access_token, app_token):
    url = f"{FEISHU_OPEN_API}/bitable/v1/apps/{app_token}"
    headers = {"Authorization": f"Bearer {tenant_access_token}"}
    return _request_json("GET", url, headers=headers)


def list_records_in_feishu_table(tenant_access_token, app_token, table_id, page_size=20, page_token=None):
    url = f"{_feishu_url(app_token, table_id)}?page_size={page_size}"
    if page_token:
        url += f"&page_token={page_token}"
    headers = {"Authorization": f"Bearer {tenant_access_token}"}
    return _request_json("GET", url, headers=headers)


def iterate_records_in_feishu_table(tenant_access_token, app_token, table_id, page_size=FEISHU_BATCH_SIZE):
    page_token = None
    while True:
        payload = list_records_in_feishu_table(
            tenant_access_token, app_token, table_id, page_size=page_size, page_token=page_token
        )
        data = payload.get("data") or {}
        items = data.get("items") or []
        for item in items:
            yield item
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")


def get_tenant_access_token(app_id, app_secret):
    url = f"{FEISHU_OPEN_API}/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {"app_id": app_id, "app_secret": app_secret}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code != 200:
        logger.error(f"Error obtaining Feishu token, status={response.status_code}, body={response.text[:500]}")
        return None

    token_response = response.json()
    if token_response.get("code") == 0:
        return token_response.get("tenant_access_token")

    logger.error(f"Error obtaining Feishu token: {token_response}")
    return None


def date_to_timestamp(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp() * 1000)


def construct_record(records):
    records_data = []
    for record in records:
        fields = dict(record["fields"])
        hyperlink = {
            "text": fields.get(csv_columns[0]),
            "link": fields.get(csv_columns[3]),
        }

        try:
            publish_timestamp = date_to_timestamp(fields.get(csv_columns[2]))
        except Exception:
            logger.error(f"Error converting publish date: {fields.get(csv_columns[2])}")
            continue

        data = {
            "fields": {
                "标题": hyperlink,
                "公众号": fields.get(csv_columns[1]),
                "发布日期": publish_timestamp,
                "摘要": fields.get(csv_columns[4]),
                "招聘批次": fields.get(csv_columns[5]),
                "地点": fields.get(csv_columns[6]),
                "时间": fields.get(csv_columns[7]),
                "标签": fields.get(csv_columns[8]),
            }
        }
        records_data.append(data)

    return records_data


def _extract_link_from_csv_record(record):
    fields = record.get("fields", record)
    return (fields.get("原文链接") or "").strip()


def _extract_title_link_from_feishu_record(record):
    title = (record.get("fields") or {}).get("标题")
    if isinstance(title, dict):
        return (title.get("link") or "").strip()
    return ""


def _normalize_csv_record(row):
    if "fields" in row:
        return {"fields": dict(row["fields"])}
    return {"fields": dict(row)}


def _search_records(feishu_url, headers, payload, page_size=FEISHU_BATCH_SIZE):
    page_token = None
    while True:
        url = f"{feishu_url}/search?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        result = _request_json("POST", url, headers=headers, payload=payload)
        data = result.get("data") or {}
        for item in data.get("items") or []:
            yield item
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")


def post_record(record, feishu_url, headers):
    response_data = _request_json("POST", feishu_url, headers=headers, payload=record)
    logger.info(f"Record added successfully: {response_data}")
    time.sleep(0.1)
    return response_data


def post_record_loop(records, feishu_url, headers):
    records = construct_record(records)
    responses = []
    for record in records:
        responses.append(post_record(record, feishu_url, headers))
    return responses


def post_record_batch(records, feishu_url, headers):
    payload_records = construct_record(records)
    if not payload_records:
        return {"code": 0, "msg": "success", "data": {"records": []}}

    data = {"records": payload_records}
    url = feishu_url + "/batch_create"
    response_data = _request_json("POST", url, headers=headers, payload=data)
    added = len((response_data.get("data") or {}).get("records") or [])
    logger.info(f"Feishu batch_create success: added={added}")
    return response_data


def delete_existing_records(records, existing_links=None):
    existing_links = existing_links or set()
    records_new = []
    seen_links = set()
    for record in records:
        wrapped = _normalize_csv_record(record)
        link = _extract_link_from_csv_record(wrapped)
        if link and (link in existing_links or link in seen_links):
            continue
        if link:
            seen_links.add(link)
        records_new.append(wrapped)
    return records_new


def query_records_title(feishu_url, headers, only_today=False):
    payload = {"field_names": ["标题"]}
    if only_today:
        payload["filter"] = {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "发布日期",
                    "operator": "is",
                    "value": ["Today", ""],
                }
            ],
        }

    titles = []
    for item in _search_records(feishu_url, headers, payload):
        link = _extract_title_link_from_feishu_record(item)
        if link:
            titles.append(link)
    return titles


def create_records(records, feishu_url, headers, existing_links=None):
    filtered_records = delete_existing_records(records, existing_links)
    skipped = len(records) - len(filtered_records)
    if not filtered_records:
        logger.info("No new Feishu records to add")
        return {"submitted": 0, "added": 0, "skipped": skipped}

    response_data = post_record_batch(filtered_records, feishu_url, headers)
    added = len((response_data.get("data") or {}).get("records") or [])
    return {
        "submitted": len(filtered_records),
        "added": added,
        "skipped": skipped,
        "response": response_data,
    }


def _read_csv_records(csv_file_path):
    rows = []
    with open(csv_file_path, "r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            rows.append({"fields": row})
    return rows


def fetch_all_record_links_from_feishu(config=None):
    app_id, app_secret, app_token, table_id = _get_main_table_config(config)
    tenant_access_token = get_tenant_access_token(app_id, app_secret)
    if not tenant_access_token:
        raise RuntimeError("Failed to obtain Feishu tenant_access_token")

    links = set()
    for item in iterate_records_in_feishu_table(tenant_access_token, app_token, table_id):
        link = _extract_title_link_from_feishu_record(item)
        if link:
            links.add(link)
    return links


def upload_rows_to_feishu(records, batch_size=FEISHU_BATCH_SIZE, config=None, existing_links=None, dedupe_only_today=False):
    app_id, app_secret, app_token, table_id = _get_main_table_config(config)
    tenant_access_token = get_tenant_access_token(app_id, app_secret)
    if not tenant_access_token:
        raise RuntimeError("Failed to obtain Feishu tenant_access_token")

    feishu_url = _feishu_url(app_token, table_id)
    headers = _build_headers(tenant_access_token)
    batch_size = min(max(batch_size, 1), FEISHU_BATCH_SIZE)

    if existing_links is None:
        if dedupe_only_today:
            existing_links = set(query_records_title(feishu_url, headers, only_today=True))
        else:
            existing_links = fetch_all_record_links_from_feishu(config=config)
    else:
        existing_links = set(existing_links)

    normalized_records = [_normalize_csv_record(record) for record in records]
    total_input = len(normalized_records)
    total_added = 0
    total_skipped = 0
    total_submitted = 0
    batches = 0

    for index in range(0, total_input, batch_size):
        raw_batch = normalized_records[index:index + batch_size]
        batch = []
        batch_seen = set()
        for record in raw_batch:
            link = _extract_link_from_csv_record(record)
            if link and (link in existing_links or link in batch_seen):
                total_skipped += 1
                continue
            if link:
                batch_seen.add(link)
            batch.append(record)

        if not batch:
            continue

        result = create_records(batch, feishu_url, headers, existing_links=set())
        total_submitted += result["submitted"]
        total_added += result["added"]
        batches += 1

        for record in batch:
            link = _extract_link_from_csv_record(record)
            if link:
                existing_links.add(link)

        time.sleep(0.1)

    summary = {
        "input_records": total_input,
        "submitted_records": total_submitted,
        "added_records": total_added,
        "skipped_records": total_skipped,
        "batches": batches,
        "existing_links": len(existing_links),
    }
    logger.info(f"Feishu upload summary: {summary}")
    return summary


def fetch_user_records_from_feishu(config=None):
    app_id, app_secret, app_token, table_id = _get_user_table_config(config)
    tenant_access_token = get_tenant_access_token(app_id, app_secret)
    if not tenant_access_token:
        raise RuntimeError("Failed to obtain Feishu tenant_access_token")

    items = list(iterate_records_in_feishu_table(tenant_access_token, app_token, table_id, page_size=200))
    payload = {
        "code": 0,
        "msg": "success",
        "data": {
            "items": items,
            "total": len(items),
            "has_more": False,
        },
    }
    logger.debug(f"Fetched Feishu user records: total={len(items)}")
    return payload


def fetch_email_list_from_feishu(config=None):
    records = fetch_user_records_from_feishu(config)

    email_list = []
    for record in (records.get("data") or {}).get("items") or []:
        email = (record.get("fields") or {}).get("邮箱")
        if email:
            email_list.append(email)
    logger.info("Email list fetched from Feishu")
    logger.info(email_list)
    return email_list


def test_fetch_records_from_feishu(config=None):
    if config is None:
        raise ValueError("config is required")
    return fetch_user_records_from_feishu(config)


class UserInfo:
    def __init__(self, name="用户", email="", need_recruiment=False, subscribed_wechats=None):
        self.name = name
        self.email = email
        self.need_recruiment = need_recruiment
        self.subscribed_wechats = subscribed_wechats
        self.prefer_style = None

    def __str__(self):
        return (
            f"Name: {self.name}, Email: {self.email}, "
            f"Need Recruiment: {self.need_recruiment}, "
            f"Subscribed Wechats: {self.subscribed_wechats}"
        )


def _normalize_email(email):
    return (email or "").strip().lower()


def _parse_need_recruitment(raw_value):
    if raw_value is None:
        return False
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, list):
        text = " ".join(str(item) for item in raw_value)
    else:
        text = str(raw_value)

    normalized = text.strip().lower()
    negative_markers = {"0", "false", "no", "n", "off"}
    if normalized in negative_markers:
        return False
    if any(marker in normalized for marker in ["否", "不需要", "不订阅", "不要", "退订", "取消", "unsubscribe", "no pandora"]):
        return False
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    return ("是" in normalized) or any(marker in normalized for marker in ["需要", "订阅", "subscribe"])


def _record_time_value(record):
    fields = record.get("fields") or {}
    candidates = [
        record.get("last_modified_time"),
        record.get("created_time"),
        fields.get("提交时间"),
        fields.get("创建时间"),
        fields.get("编号"),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            continue
        try:
            return float(text)
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def get_users_info_from_records(records):
    user_info_list = []
    items = (records.get("data") or {}).get("items") or []
    indexed_items = list(enumerate(items))
    if any(_record_time_value(record) is not None for _, record in indexed_items):
        indexed_items.sort(key=lambda item: (_record_time_value(item[1]) or 0, item[0]))

    latest_users_by_email = {}
    for _, record in indexed_items:
        try:
            fields = record.get("fields") or {}
            user_info = UserInfo()
            name = fields.get("您希望我们怎么称呼您？【beta，还在灰度测试】")
            user_info.name = name if name else "用户"
            prefer_style = fields.get("您希望看到哪种风格的报告？【beta，还在灰度测试】")
            user_info.prefer_style = prefer_style if prefer_style else "通用"
            user_info.email = _normalize_email(fields.get("邮箱"))
            if not user_info.email:
                continue
            user_info.need_recruiment = _parse_need_recruitment(
                fields.get("是否需要【Pandora招聘信息分享】订阅？")
            )

            subscribed_wechats = fields.get(
                "请输入要个性化订阅的公众号名称【多个请换行或用空格分开】 （目前限制在30个以内，因需要一定的手动操作，暂不保证及时生效）"
            )
            if subscribed_wechats:
                subscribed_wechats = re.split(r"[\n\s,，]+", subscribed_wechats)
                subscribed_wechats = [item.strip() for item in subscribed_wechats if item.strip()]
                user_info.subscribed_wechats = [element for element in subscribed_wechats if element]
        except Exception as e:
            logger.error(e)
            continue

        latest_users_by_email[user_info.email] = user_info
    user_info_list.extend(latest_users_by_email.values())
    return user_info_list


def fetch_user_info_from_feishu(config=None):
    records = fetch_user_records_from_feishu(config)
    return get_users_info_from_records(records)


def fetch_user_info_from_feishu_and_update_database(config=None):
    user_info = fetch_user_info_from_feishu(config)
    if user_info:
        process_user_batch(user_info)

    return user_info


def test_fetch_user_info_from_feishu(config=None):
    records = test_fetch_records_from_feishu(config)
    user_info_list = get_users_info_from_records(records)
    for user_info in user_info_list:
        print(user_info)
    return user_info_list


def test_fetch_email_list_from_feishu(config=None):
    return fetch_email_list_from_feishu(config)


def upload_to_feishu(csv_file_path, batch_size=FEISHU_BATCH_SIZE, config=None):
    rows = _read_csv_records(csv_file_path)
    summary = upload_rows_to_feishu(
        rows,
        batch_size=batch_size or _get_batch_size(config),
        config=config,
        dedupe_only_today=True,
    )
    logger.info(f"All records are uploaded to Feishu: {summary}")
    return summary


def iter_local_csv_records(data_dir, start_date=None, end_date=None):
    data_path = Path(data_dir)
    for path in sorted(data_path.glob("*_招聘信息汇总.csv")):
        source_date = path.name.split("_", 1)[0]
        if start_date and source_date < start_date:
            continue
        if end_date and source_date > end_date:
            continue

        with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if not (row.get("原文链接") or row.get("标题")):
                    continue
                yield {
                    "fields": row,
                    "__source_file": str(path),
                    "__source_date": source_date,
                }


def compare_local_csvs_with_feishu(data_dir, config=None, start_date=None, end_date=None):
    existing_links = fetch_all_record_links_from_feishu(config=config)
    local_total_rows = 0
    local_unique_links = set()
    missing_rows = []
    missing_links = set()
    missing_by_day = Counter()
    local_by_day = Counter()

    for record in iter_local_csv_records(data_dir, start_date=start_date, end_date=end_date):
        local_total_rows += 1
        source_date = record["__source_date"]
        local_by_day[source_date] += 1

        link = _extract_link_from_csv_record(record)
        if not link:
            continue
        local_unique_links.add(link)
        if link in existing_links or link in missing_links:
            continue

        missing_rows.append(record)
        missing_links.add(link)
        missing_by_day[source_date] += 1

    summary = {
        "data_dir": str(data_dir),
        "start_date": start_date,
        "end_date": end_date,
        "local_total_rows": local_total_rows,
        "local_unique_links": len(local_unique_links),
        "feishu_existing_links": len(existing_links),
        "missing_unique_links": len(missing_links),
        "missing_rows": missing_rows,
        "missing_by_day": dict(sorted(missing_by_day.items())),
        "local_by_day": dict(sorted(local_by_day.items())),
        "existing_links": existing_links,
    }
    return summary


def backfill_feishu_from_local_csvs(
    data_dir,
    config=None,
    start_date=None,
    end_date=None,
    max_records=None,
    batch_size=FEISHU_BATCH_SIZE,
    dry_run=False,
):
    comparison = compare_local_csvs_with_feishu(
        data_dir=data_dir,
        config=config,
        start_date=start_date,
        end_date=end_date,
    )
    missing_rows = comparison["missing_rows"]
    if max_records is not None:
        missing_rows = missing_rows[:max_records]

    result = {
        "compare": {
            "local_total_rows": comparison["local_total_rows"],
            "local_unique_links": comparison["local_unique_links"],
            "feishu_existing_links": comparison["feishu_existing_links"],
            "missing_unique_links": len(comparison["missing_rows"]),
            "missing_by_day": comparison["missing_by_day"],
        }
    }

    if dry_run or not missing_rows:
        result["upload"] = {
            "dry_run": dry_run,
            "input_records": len(missing_rows),
            "submitted_records": 0,
            "added_records": 0,
            "skipped_records": 0,
            "batches": 0,
        }
        return result

    upload_summary = upload_rows_to_feishu(
        missing_rows,
        batch_size=batch_size,
        config=config,
        existing_links=comparison["existing_links"],
        dedupe_only_today=False,
    )
    result["upload"] = upload_summary
    return result


def find_csv_filenames(path_to_dir, suffix=".csv"):
    filenames = os.listdir(path_to_dir)
    return [filename for filename in filenames if filename.endswith(suffix)]


def main():
    csv_file_path = r"D:\yy\wechatmonitor\public\2024-03-07_招聘信息汇总.csv"
    raise SystemExit(
        "This module is intended to be imported. Use upload_to_feishu(...) or backfill_feishu_from_local_csvs(...). "
        f"Legacy example path: {csv_file_path}"
    )


if __name__ == "__main__":
    main()
