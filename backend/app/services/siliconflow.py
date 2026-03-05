from typing import Any

import httpx

from app.config import Settings


class SiliconFlowError(RuntimeError):
    pass


class SiliconFlowClient:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.siliconflow_api_key
        self._chat_url = f"{settings.siliconflow_base_url.rstrip('/')}/chat/completions"
        self._timeout = settings.siliconflow_timeout_seconds

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise SiliconFlowError("SILICONFLOW_API_KEY is empty.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._chat_url, headers=headers, json=payload)

        if response.status_code >= 400:
            raise SiliconFlowError(
                f"SiliconFlow request failed ({response.status_code}): {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise SiliconFlowError(f"SiliconFlow returned non-JSON response: {response.text}") from exc
