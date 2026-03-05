from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    siliconflow_api_key: str = Field(default="", validation_alias="SILICONFLOW_API_KEY")
    siliconflow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        validation_alias="SILICONFLOW_BASE_URL",
    )
    siliconflow_model: str = Field(
        default="Qwen/Qwen3-8B",
        validation_alias="SILICONFLOW_MODEL",
    )
    siliconflow_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="SILICONFLOW_TIMEOUT_SECONDS",
    )

    mcp_server_url: str = Field(
        default="http://100.68.129.231:8000/mcp",
        validation_alias="MCP_SERVER_URL",
    )
    mcp_accept: str = Field(
        default="application/json, text/event-stream",
        validation_alias="MCP_ACCEPT",
    )
    mcp_content_type: str = Field(default="application/json", validation_alias="MCP_CONTENT_TYPE")
    mcp_access_token: str = Field(default="", validation_alias="MCP_ACCESS_TOKEN")
    mcp_timeout_seconds: float = Field(default=60.0, validation_alias="MCP_TIMEOUT_SECONDS")
    mcp_login_url: str = Field(default="", validation_alias="MCP_LOGIN_URL")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_mcp_login_url(self) -> str:
        if self.mcp_login_url.strip():
            return self.mcp_login_url.strip()

        parsed = urlsplit(self.mcp_server_url.strip())
        path = parsed.path.rstrip("/")
        if path.endswith("/mcp"):
            path = path[: -len("/mcp")]
        if not path:
            path = ""
        return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/login", "", ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
