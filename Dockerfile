FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    CRON_TZ=Asia/Shanghai \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    DATABASE_URL=sqlite:////app/data/message_monitor.db \
    WECHAT_SQLITE_DB_PATH=/app/data/message_monitor.db \
    WECHAT2RSS_BASE=http://host.docker.internal:8081

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        cron \
        procps \
        tzdata \
        curl \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        fonts-noto-cjk \
        wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

COPY requirements-docker.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-docker.txt

COPY . .
RUN chmod +x scripts/*.sh docker/entrypoint.sh

CMD ["/app/docker/entrypoint.sh"]
