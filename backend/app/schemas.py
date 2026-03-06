from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    user_id: str
    expires_in: int = 7200
    expires_at: int


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    max_steps: int = 8
    use_mcp: bool = True


class ToolTrace(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_preview: str


class ChatResponse(BaseModel):
    reply: str
    reasoning: str | None = None
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    usage: dict[str, Any] | None = None
