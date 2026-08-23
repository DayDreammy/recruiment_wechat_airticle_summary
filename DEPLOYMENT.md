# Deployment

## 架构（2026-08-23 简化版）

纯本地链路，不依赖任何远程服务：

```
本机 wechat2rss (127.0.0.1:8081)
        │ 聚合 feed（每小时）
        ▼
本地 sqlite（wechat_articles + processed_articles + users）
        │ 每日 8:30 汇总（DeepSeek 分类/摘要/关键信息）
        ▼
飞书表格上传 + 订阅邮件 + CSV/Excel
```

后端存储全部在本地 sqlite（`data/message_monitor.db`）；用户与订阅关系
每次汇总前从飞书问卷表同步到本地。已移除 NocoDB / 远程 MySQL / server421 隧道。

## 环境准备

1. 本机运行 wechat2rss（`127.0.0.1:8081`），容器通过
   `host.docker.internal` 访问它（compose 已配置 `extra_hosts`）。
2. `config.json`（gitignored，含 DeepSeek/飞书密钥）按
   `config.template.json` 创建；`table_backend` 固定为 `feishu`。
3. `.env`（gitignored）至少包含：
   - `WECHAT2RSS_RSS_TOKEN`（本机 wechat2rss 的 RSS token）
   - `DATABASE_URL=sqlite:////app/data/message_monitor.db`（容器内路径）
   - `WECHAT_SQLITE_DB_PATH=/app/data/message_monitor.db`

## 构建镜像

```bash
docker compose build
```

镜像说明：
- 基于 `python:3.10-slim`，安装 `wkhtmltopdf`（PDF 生成）与 CJK 字体；
- 不包含 PaddleOCR（保持镜像精简），图片型文章 OCR 回退为空文本；
- 容器内 cron 负责调度：每小时抓取、每日 8:30 汇总（Asia/Shanghai）。

## 生产环境（cron 常驻）

```bash
docker compose up -d          # 生产容器 recruiment-prod
docker compose logs -f        # 查看日志
```

数据目录（宿主机）：
- `./data`：sqlite + CSV/Excel + 聚合 feed
- `./pdfs`：文章 PDF
- `./logs`：`cron.log` / `rss_fetcher.log` / `summary.log` / `build_feed.log`

首次启动容器会先补抓一次，然后 cron 接管。

## 测试环境（与生产隔离）

测试环境与生产共用同一镜像，但使用独立的数据/日志/配置目录，不启动 cron：

```bash
# 准备测试配置（内容复制自生产 config.json 或按需调整）
cp config.json config.test.json
cp .env .env.test

# 单次跑抓取（dry-run，不写库）
docker compose -f docker-compose.yml -f docker-compose.test.yml \
  run --rm recruiment \
  python rss_article_fetcher_enhanced.py --dry-run \
    --rss-url "file:///app/data/recruitment_feed.xml" \
    --db-path /app/data/message_monitor.db --pdf-dir /app/pdfs

# 单次跑汇总（只处理"昨天"，会写测试库 + 发测试飞书/邮件）
docker compose -f docker-compose.yml -f docker-compose.test.yml \
  run --rm recruiment /app/scripts/run_summary.sh
```

测试环境数据落在 `./data-test`、`./logs-test`、`./pdfs-test`，与生产互不影响。
新功能先在测试环境验证，再切生产。

## 版本管理

远程仓库：`https://github.com/DayDreammy/recruiment_wechat_airticle_summary`

- 主分支保留线上稳定版；新功能在独立分支开发并推远程，验证通过后合入。
- `config.json`、`.env`、`data/`、`logs/`、`pdfs/`、`.venv` 均不入库；
  用 `config.template.json` 与 `.env.example` 作为共享模板。
