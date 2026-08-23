import json


csv_columns = ['标题', '公众号', '发布日期', '原文链接', '摘要', '招聘批次', '地点', '时间', '标签']


def read_config(config_path):
    try:
        print(f"Reading config from {config_path}")
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
            return config
    except FileNotFoundError:
        print(f"Error: The file {config_path} was not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: The file {config_path} could not be parsed.")
        return None
