# RSS公众号文章爬取脚本

## 功能概述

该脚本从RSS订阅源获取微信公众号文章信息，自动存储到数据库中，并生成PDF文件保存完整的文章内容。

## 主要功能

- 🔄 **增量更新**: 自动检测新文章，避免重复插入
- 📄 **PDF生成**: 将HTML内容转换为PDF文件保存
- 🗄️ **数据库存储**: 存储文章元信息到SQLite数据库
- 📝 **完整日志**: 记录运行过程和错误信息
- ⚙️ **定时运行**: 支持cron job定时执行
- 🛡️ **错误处理**: 优雅处理各种异常情况

## 文件说明

- `rss_article_fetcher.py` - 基础版本脚本（仅数据库存储）
- `rss_article_fetcher_enhanced.py` - 增强版脚本（包含PDF生成）
- `test_pdf_generation.py` - PDF生成功能测试脚本
- `setup_cron.sh` - cron job设置脚本

## 使用方法

### 基础运行

```bash
# 干运行模式（不实际插入数据库）
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --dry-run

# 正常运行
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py

# 跳过PDF生成（仅数据库存储）
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --skip-pdf

# 详细输出
~/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py --verbose
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--dry-run` | 试运行模式，不实际插入数据库 | False |
| `--skip-pdf` | 跳过PDF生成 | False |
| `--rss-url` | RSS订阅地址 | 默认配置的地址 |
| `--db-path` | 数据库文件路径 | `/home/yy/project/Gewechat/vxbot/data/message_monitor.db` |
| `--pdf-dir` | PDF保存目录 | `./pdfs` |
| `--verbose` | 详细输出 | False |

## 数据库结构

脚本将数据存储到 `wechat_articles` 表中：

- `message_id` - 文章唯一标识符
- `title` - 文章标题
- `url` - 微信文章链接
- `account_name` - 公众号名称
- `content` - 文章纯文本内容
- `raw_data` - 原始HTML内容
- `pdf_path` - 生成的PDF文件路径
- `created_at` - 发布时间
- `processed` - 是否已处理
- `article_type` - 文章类型（默认: wechat）

## 定时任务设置

### 安装cron job

```bash
# 运行设置脚本
chmod +x setup_cron.sh
./setup_cron.sh

# 手动添加（每小时运行一次）
(crontab -l 2>/dev/null; echo '0 * * * * cd /home/yy/project/recruiment_article_summary && /home/yy/anaconda3/envs/py310/bin/python rss_article_fetcher_enhanced.py >> cron.log 2>&1') | crontab -
```

### 推荐的运行频率

- **高频更新**: 每15分钟 `*/15 * * * *`
- **常规更新**: 每小时 `0 * * * *` (推荐)
- **低频更新**: 每4小时 `0 */4 * * *`
- **定时更新**: 每天3次 `0 8,14,20 * * *`

## 日志文件

- `rss_fetcher_enhanced.log` - 详细运行日志
- `cron.log` - cron job运行日志

查看日志：
```bash
# 查看最新日志
tail -f rss_fetcher_enhanced.log

# 查看cron运行日志
tail -f cron.log
```

## 故障排除

### 常见问题

1. **权限错误**
   ```bash
   chmod +x rss_article_fetcher_enhanced.py
   ```

2. **依赖包缺失**
   ```bash
   ~/anaconda3/envs/py310/bin/python -m pip install requests beautifulsoup4 pdfkit
   ```

3. **PDF生成失败**
   - 检查wkhtmltopdf是否安装：`which wkhtmltopdf`
   - 使用 `--skip-pdf` 参数跳过PDF生成

4. **数据库连接失败**
   - 检查数据库文件路径是否正确
   - 确保有读写权限

### 测试功能

```bash
# 测试PDF生成
~/anaconda3/envs/py310/bin/python test_pdf_generation.py

# 测试数据库连接
~/anaconda3/envs/py310/bin/python -c "
import sqlite3
conn = sqlite3.connect('/home/yy/project/Gewechat/vxbot/data/message_monitor.db')
print('数据库连接成功')
conn.close()
"
```

## 系统要求

- Python 3.10+
- SQLite3
- wkhtmltopdf (PDF生成)
- 依赖包：requests, beautifulsoup4, pdfkit

## 数据流向

```
RSS订阅源 → 解析文章 → 增量检查 → 生成PDF → 存储数据库 → pdfsummary.py处理
```

这个脚本是 `pdfsummary.py` 的上游工作，为后续的文章处理提供数据源。 