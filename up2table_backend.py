import logging

from up2feishu import fetch_user_info_from_feishu_and_update_database, upload_to_feishu
from sqldb import process_user_batch

logger = logging.getLogger("pdfsummary")


def upload_recruitment_table(csv_file_path, config=None):
    logger.info("Uploading recruitment records to Feishu")
    return upload_to_feishu(csv_file_path, config=config)


def fetch_user_info_and_update_database(config=None):
    logger.info("Syncing users from Feishu")
    return fetch_user_info_from_feishu_and_update_database(config=config)
