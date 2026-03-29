from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from openai import OpenAI

from .config import SETTINGS


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=SETTINGS.llm_api_key,
            base_url=SETTINGS.llm_base_url,
            timeout=SETTINGS.llm_timeout_seconds,
        )

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(SETTINGS.llm_max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=SETTINGS.llm_model,
                    temperature=SETTINGS.llm_temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                return self._parse_json(content)
            except Exception as exc:
                last_error = exc
                if attempt >= SETTINGS.llm_max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def _parse_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        fence_match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if fence_match:
            return json.loads(fence_match.group(0))

        raise ValueError("Model response is not valid JSON")


LLM = LLMClient()
