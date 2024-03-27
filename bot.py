from openai import OpenAI
from zhipuai import ZhipuAI

import logging
logger = logging.getLogger()


class Bot():
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model

    def get_response(self, system_prompt, text):
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
            )

            response = completion.choices[0].message.content.strip()
            print(f"OpenAI API response: {response}")
        except Exception as e:
            logger.exception(f"openai response failed : {e}")
            return ""

        return response


class OpenaiBot(Bot):
    def __init__(self, api_key, base_url="", model=""):
        super().__init__(api_key, model)
        if base_url == "":
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = OpenAI(api_key=api_key, base_url=base_url)


class ZhipuBot(Bot):
    def __init__(self, api_key, model=""):
        super().__init__(api_key, model)
        self.client = ZhipuAI(api_key=api_key)
