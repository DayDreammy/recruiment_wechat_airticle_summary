from openai import OpenAI
import base64
import os
import random
import time
# from zhipuai import ZhipuAI

import logging
logger = logging.getLogger("pdfsummary")


def read_int_env(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Ignore invalid {name}={value}, fallback to {default}")
        return default


def read_float_env(name, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Ignore invalid {name}={value}, fallback to {default}")
        return default


# Function to encode the image


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


class Bot():
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model
        self.retry_attempts = read_int_env("LLM_RETRY_ATTEMPTS", 5)
        self.retry_base_seconds = read_float_env("LLM_RETRY_BASE_SECONDS", 1)
        self.retry_max_seconds = read_float_env("LLM_RETRY_MAX_SECONDS", 20)

    def _is_retryable_error(self, error):
        status_code = getattr(error, "status_code", None)
        if status_code in (408, 409, 429):
            return True
        if status_code is not None and status_code >= 500:
            return True
        error_name = error.__class__.__name__.lower()
        return any(
            marker in error_name
            for marker in ("timeout", "connection", "ratelimit", "internalserver")
        )

    def _retry_delay(self, attempt):
        delay = self.retry_base_seconds * (2 ** (attempt - 1))
        delay = min(delay, self.retry_max_seconds)
        return delay + random.uniform(0, min(0.5, delay / 4))

    def get_response(self, system_prompt="", text="", img_paths=None, show_log=False):
        text = text or ""
        system_prompt = system_prompt or ""
        if not text.strip() and not img_paths:
            logger.warning("Skip LLM request because user content is empty")
            return ""

        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})

        user_content = text
        if img_paths:
            # 统一处理为列表格式（支持字符串路径或路径列表）
            if not isinstance(img_paths, list):
                img_paths = [img_paths]

            # 多模态请求使用 content parts；纯文本请求则使用字符串更稳定。
            user_content = [{"type": "text", "text": text}]

            # 添加多个图片内容
            for img_path in img_paths:
                base64_image = encode_image(img_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })

        messages.append({"role": "user", "content": user_content})

        for attempt in range(1, self.retry_attempts + 1):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                )

                response = completion.choices[0].message.content.strip()
                if show_log:
                    logger.info(f"API response: {response}")
                return response
            except Exception as e:
                if attempt < self.retry_attempts and self._is_retryable_error(e):
                    delay = self._retry_delay(attempt)
                    logger.warning(
                        f"LLM request failed on attempt {attempt}/{self.retry_attempts}; "
                        f"retry in {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    continue

                logger.exception(
                    f"response failed after {attempt}/{self.retry_attempts} attempts: {e}")
                return ""


class OpenaiBot(Bot):
    def __init__(self, api_key, base_url="", model=""):
        super().__init__(api_key, model)
        timeout_seconds = read_float_env("OPENAI_TIMEOUT_SECONDS", 30)
        max_retries = read_int_env("OPENAI_MAX_RETRIES", 0)

        client_kwargs = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": max_retries,
        }
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        logger.info(
            f"OpenAI client settings: timeout={timeout_seconds}s, max_retries={max_retries}")


# class ZhipuBot(Bot):
#     def __init__(self, api_key, model=""):
#         super().__init__(api_key, model)
#         self.client = ZhipuAI(api_key=api_key)
