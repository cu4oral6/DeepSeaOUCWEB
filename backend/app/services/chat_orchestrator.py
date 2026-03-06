import json
from typing import Any

from app.schemas import ChatRequest, ChatResponse, ToolTrace
from app.services.mcp_client import MCPClientError, RemoteMCPClient
from app.services.siliconflow import SiliconFlowClient, SiliconFlowError


class ChatOrchestrator:
    def __init__(
        self,
        siliconflow_client: SiliconFlowClient,
        mcp_client: RemoteMCPClient,
        default_model: str,
        user_access_token: str | None = None,
    ) -> None:
        self._siliconflow = siliconflow_client
        self._mcp = mcp_client
        self._default_model = default_model
        self._user_access_token = user_access_token

    @staticmethod
    def _to_openai_tool_schema(mcp_tool: dict[str, Any]) -> dict[str, Any]:
        input_schema = mcp_tool.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        if "type" not in input_schema:
            input_schema["type"] = "object"

        return {
            "type": "function",
            "function": {
                "name": mcp_tool["name"],
                "description": mcp_tool.get("description", ""),
                "parameters": input_schema,
            },
        }

    @staticmethod
    def _serialize_tool_result(result: dict[str, Any]) -> str:
        if "structuredContent" in result:
            return json.dumps(result["structuredContent"], ensure_ascii=False)

        content = result.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    text_parts.append(str(item))
                    continue
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                else:
                    text_parts.append(json.dumps(item, ensure_ascii=False))
            return "\n".join([part for part in text_parts if part]).strip()

        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _tool_requires_access_token(mcp_tool: dict[str, Any]) -> bool:
        input_schema = mcp_tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            return False

        properties = input_schema.get("properties")
        if isinstance(properties, dict) and "access_token" in properties:
            return True

        required = input_schema.get("required")
        if isinstance(required, list) and "access_token" in required:
            return True

        return False

    @staticmethod
    def _is_placeholder_token(value: Any) -> bool:
        if value is None:
            return True
        if not isinstance(value, str):
            return False

        normalized = value.strip().lower()
        return normalized in {
            "",
            "null",
            "none",
            "undefined",
            "your_access_token_here",
            "access_token_here",
            "<access_token>",
            "{access_token}",
        }

    def _inject_access_token(
        self,
        arguments: dict[str, Any],
        tool_requires_token: bool,
    ) -> dict[str, Any]:
        if not self._user_access_token:
            return arguments

        if "access_token" in arguments:
            if self._is_placeholder_token(arguments.get("access_token")):
                arguments["access_token"] = self._user_access_token
            return arguments

        if tool_requires_token:
            arguments["access_token"] = self._user_access_token
        return arguments

    async def run_chat(self, request: ChatRequest) -> ChatResponse:
        if not request.messages:
            raise ValueError("messages cannot be empty")

        model = request.model or self._default_model
        messages = [item.model_dump(exclude_none=True) for item in request.messages]
        traces: list[ToolTrace] = []
        assistant_segments: list[str] = []
        tool_requires_access_token: dict[str, bool] = {}

        tools_for_model: list[dict[str, Any]] | None = None
        if request.use_mcp:
            try:
                mcp_tools = await self._mcp.list_tools()
                tools_for_model = [self._to_openai_tool_schema(tool) for tool in mcp_tools]
                for tool in mcp_tools:
                    name = tool.get("name")
                    if isinstance(name, str) and name:
                        tool_requires_access_token[name] = self._tool_requires_access_token(tool)
            except MCPClientError as exc:
                raise RuntimeError(f"MCP tools/list failed: {exc}") from exc

        last_usage: dict[str, Any] | None = None
        last_reasoning: str | None = None

        total_steps = max(request.max_steps, 1)
        for step_index in range(total_steps):
            try:
                response = await self._siliconflow.chat(
                    messages=messages,
                    model=model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    tools=tools_for_model,
                )
            except SiliconFlowError as exc:
                raise RuntimeError(f"SiliconFlow call failed: {exc}") from exc

            last_usage = response.get("usage")
            choices = response.get("choices", [])
            if not choices:
                raise RuntimeError(f"SiliconFlow returned no choices: {response}")

            first_choice = choices[0]
            assistant_message = first_choice.get("message", {})
            finish_reason = first_choice.get("finish_reason")
            assistant_content = assistant_message.get("content") or ""
            last_reasoning = assistant_message.get("reasoning_content") or last_reasoning
            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                if assistant_content:
                    assistant_segments.append(assistant_content)

                if finish_reason == "length" and step_index < total_steps - 1:
                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Continue from exactly where you stopped. "
                                "Do not repeat previously generated text."
                            ),
                        }
                    )
                    continue

                return ChatResponse(
                    reply="".join(assistant_segments).strip() or "(empty response)",
                    reasoning=last_reasoning,
                    tool_traces=traces,
                    usage=last_usage,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                function_info = tool_call.get("function", {})
                tool_name = function_info.get("name")
                raw_arguments = function_info.get("arguments", "{}")
                tool_call_id = tool_call.get("id")

                if not tool_name:
                    continue
                try:
                    arguments = json.loads(raw_arguments) if raw_arguments else {}
                    if not isinstance(arguments, dict):
                        arguments = {"input": arguments}
                except json.JSONDecodeError:
                    arguments = {"raw_arguments": raw_arguments}

                requires_token = tool_requires_access_token.get(tool_name, False)
                arguments = self._inject_access_token(arguments, tool_requires_token=requires_token)

                try:
                    mcp_result = await self._mcp.call_tool(tool_name, arguments)
                    tool_output_text = self._serialize_tool_result(mcp_result)
                except Exception as exc:
                    tool_output_text = f"Tool call failed: {exc}"

                trace_arguments = dict(arguments)
                if "access_token" in trace_arguments:
                    trace_arguments["access_token"] = "***"

                traces.append(
                    ToolTrace(
                        tool_name=tool_name,
                        arguments=trace_arguments,
                        result_preview=tool_output_text[:1200],
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": tool_output_text,
                    }
                )

        return ChatResponse(
            reply="Reached max_steps before a final answer was produced.",
            reasoning=last_reasoning,
            tool_traces=traces,
            usage=last_usage,
        )
