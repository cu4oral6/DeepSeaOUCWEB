import json
from itertools import count
from typing import Any

import httpx

from app.config import Settings


class MCPClientError(RuntimeError):
    pass


class RemoteMCPClient:
    def __init__(self, settings: Settings, access_token: str | None = None) -> None:
        self._url = settings.mcp_server_url
        self._accept = settings.mcp_accept
        self._content_type = settings.mcp_content_type
        self._access_token = access_token if access_token is not None else settings.mcp_access_token
        self._timeout = settings.mcp_timeout_seconds
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._initialized = False
        self._counter = count(1)
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": self._accept,
            "Content-Type": self._content_type,
        }
        if self._access_token:
            headers["access_token"] = self._access_token
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _remember_session(self, response: httpx.Response) -> None:
        session_id = (
            response.headers.get("MCP-Session-Id")
            or response.headers.get("Mcp-Session-Id")
            or response.headers.get("mcp-session-id")
        )
        if session_id:
            self._session_id = session_id

    def _decode_rpc_message(self, body: str, content_type: str, request_id: int) -> dict[str, Any]:
        content_type = content_type.lower()
        raw = body.strip()

        if "application/json" in content_type or raw.startswith("{") or raw.startswith("["):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise MCPClientError(f"MCP returned invalid JSON: {raw}") from exc

            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and item.get("id") == request_id:
                        return item
                if payload and isinstance(payload[0], dict):
                    first = payload[0]
                    if "result" in first or "error" in first:
                        return first
                    return {"result": first}
                raise MCPClientError(f"MCP returned unsupported list payload: {payload}")

            if isinstance(payload, dict):
                if "result" in payload or "error" in payload:
                    return payload
                return {"result": payload}

            raise MCPClientError(f"MCP returned unsupported payload: {payload}")

        if "text/event-stream" in content_type:
            last_data: dict[str, Any] | None = None
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("id") == request_id and ("result" in chunk or "error" in chunk):
                    return chunk
                last_data = chunk

            if last_data:
                if "result" in last_data or "error" in last_data:
                    return last_data
                return {"result": last_data}

        raise MCPClientError(f"Unable to decode MCP response ({content_type}): {body}")

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = next(self._counter)
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        response = await self._client.post(
            self._url,
            headers=self._build_headers(),
            json=payload,
        )
        self._remember_session(response)

        if response.status_code == 404 and self._session_id:
            self._session_id = None
            self._protocol_version = None
            self._initialized = False

        if response.status_code < 200 or response.status_code >= 300:
            location = response.headers.get("location", "")
            raise MCPClientError(
                f"MCP request failed ({response.status_code}). "
                f"location={location or '-'} body={response.text[:500]}"
            )

        if not response.text.strip():
            content_type = response.headers.get("content-type", "")
            location = response.headers.get("location", "")
            raise MCPClientError(
                f"MCP returned empty body (status={response.status_code}, "
                f"content-type={content_type or '-'}, location={location or '-'})."
            )

        rpc_message = self._decode_rpc_message(
            body=response.text,
            content_type=response.headers.get("content-type", ""),
            request_id=request_id,
        )
        if "error" in rpc_message:
            raise MCPClientError(f"MCP error: {rpc_message['error']}")
        result = rpc_message.get("result")
        if result is None:
            raise MCPClientError(f"MCP response has no result field: {rpc_message}")
        return result

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        response = await self._client.post(
            self._url,
            headers=self._build_headers(),
            json=payload,
        )
        self._remember_session(response)

    async def _initialize(self) -> None:
        if self._initialized:
            return

        protocol_versions = ["2025-06-18", "2025-03-26", "2024-11-05"]
        last_error: Exception | None = None

        for version in protocol_versions:
            try:
                result = await self._rpc(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "deepsea-web-chat",
                            "version": "0.1.0",
                        },
                    },
                )
                negotiated_version = result.get("protocolVersion")
                self._protocol_version = negotiated_version if isinstance(negotiated_version, str) else version
                self._initialized = True
                break
            except Exception as exc:
                last_error = exc

        if not self._initialized:
            raise MCPClientError(f"MCP initialize failed: {last_error}")

        try:
            await self._notify("notifications/initialized")
        except Exception:
            pass

    async def list_tools(self) -> list[dict[str, Any]]:
        await self._initialize()
        result = await self._rpc("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPClientError(f"Unexpected tools/list response: {result}")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self._initialize()
        result = await self._rpc(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        if not isinstance(result, dict):
            return {"content": [{"type": "text", "text": str(result)}]}
        return result
