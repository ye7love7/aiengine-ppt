from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from openai import OpenAI

from .config import SETTINGS
from .storage import STORE


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=SETTINGS.llm_api_key,
            base_url=SETTINGS.llm_base_url,
            timeout=SETTINGS.llm_timeout_seconds,
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        *,
        task_id: Optional[str] = None,
        stage_label: str = "llm",
    ) -> dict[str, Any]:
        request_payload = {
            "base_url": SETTINGS.llm_base_url,
            "api_key": SETTINGS.llm_api_key,
            "model": SETTINGS.llm_model,
            "timeout_seconds": SETTINGS.llm_timeout_seconds,
            "temperature": SETTINGS.llm_temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        self._emit_request_logs(task_id, stage_label, request_payload)

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

                response_payload = self._dump_response(response)
                self._emit_response_logs(task_id, stage_label, response_payload)

                choices = response_payload.get("choices")
                if not choices:
                    raise ValueError("LLM response missing choices")
                message = choices[0].get("message")
                if not isinstance(message, dict):
                    raise ValueError("LLM response missing message")
                content = message.get("content")
                if not content:
                    raise ValueError("LLM response missing content")
                return self._parse_json(str(content))
            except Exception as exc:
                last_error = exc
                self._emit_error_log(task_id, stage_label, attempt, exc)
                if attempt >= SETTINGS.llm_max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM request failed: {last_error}") from last_error

    def _emit_request_logs(self, task_id: Optional[str], stage_label: str, payload: dict[str, Any]) -> None:
        if not task_id:
            return
        STORE.write_stage_metadata(task_id, f"{stage_label}_llm_request", payload)
        STORE.append_log(
            task_id,
            f"[LLM:{stage_label}] request base_url={payload['base_url']} model={payload['model']} api_key={payload['api_key']}",
        )
        STORE.append_log(task_id, f"[LLM:{stage_label}] system_prompt:\n{payload['system_prompt']}")
        STORE.append_log(task_id, f"[LLM:{stage_label}] user_prompt:\n{payload['user_prompt']}")

    def _emit_response_logs(self, task_id: Optional[str], stage_label: str, payload: dict[str, Any]) -> None:
        if not task_id:
            return
        STORE.write_stage_metadata(task_id, f"{stage_label}_llm_response", payload)
        STORE.append_log(task_id, f"[LLM:{stage_label}] raw_response:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")

    def _emit_error_log(self, task_id: Optional[str], stage_label: str, attempt: int, exc: Exception) -> None:
        if not task_id:
            return
        STORE.append_log(task_id, f"[LLM:{stage_label}] attempt={attempt + 1} failed: {exc}")

    def _dump_response(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            payload = response.model_dump()
            if isinstance(payload, dict):
                return payload
        if isinstance(response, dict):
            return response
        raise ValueError("LLM response is not serializable")

    def _parse_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        fence_match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if fence_match:
            return json.loads(fence_match.group(0))

        raise ValueError("Model response is not valid JSON")


LLM = LLMClient()
