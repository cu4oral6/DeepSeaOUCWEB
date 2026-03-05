import time
from typing import Any

import httpx

from app.config import Settings
from app.schemas import LoginRequest, LoginResponse


class MCPAuthError(RuntimeError):
    pass


class MCPAuthClient:
    def __init__(self, settings: Settings) -> None:
        self._login_url = settings.resolved_mcp_login_url
        self._timeout = settings.mcp_timeout_seconds
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def login(self, payload: LoginRequest) -> LoginResponse:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.post(
                self._login_url,
                headers=self._headers,
                json=payload.model_dump(),
            )

        if response.status_code < 200 or response.status_code >= 300:
            raise MCPAuthError(f"MCP login failed ({response.status_code}): {response.text}")

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise MCPAuthError(f"MCP login returned non-JSON body: {response.text}") from exc

        access_token = body.get("access_token")
        user_id = body.get("user_id")
        if not isinstance(access_token, str) or not access_token:
            raise MCPAuthError(f"MCP login response missing access_token: {body}")
        if not isinstance(user_id, str) or not user_id:
            raise MCPAuthError(f"MCP login response missing user_id: {body}")

        expires_in = 7200
        expires_at = int(time.time()) + expires_in
        return LoginResponse(
            access_token=access_token,
            user_id=user_id,
            expires_in=expires_in,
            expires_at=expires_at,
        )

