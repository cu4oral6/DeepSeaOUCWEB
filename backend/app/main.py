from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.schemas import ChatRequest, ChatResponse, LoginRequest, LoginResponse
from app.services.chat_orchestrator import ChatOrchestrator
from app.services.mcp_auth import MCPAuthClient, MCPAuthError
from app.services.mcp_client import MCPClientError, RemoteMCPClient
from app.services.siliconflow import SiliconFlowClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    siliconflow_client = SiliconFlowClient(settings)
    auth_client = MCPAuthClient(settings)
    app.state.settings = settings
    app.state.siliconflow_client = siliconflow_client
    app.state.auth_client = auth_client
    yield


def _extract_mcp_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    token = request.headers.get("X-MCP-Access-Token", "").strip()
    if token:
        return token

    raise HTTPException(status_code=401, detail="Missing MCP access token. Please login first.")


def _is_unauthorized_error(message: str) -> bool:
    text = message.lower()
    return "401" in text or "unauthorized" in text or "forbidden" in text


settings = get_settings()
app = FastAPI(
    title="DeepSea OUC MCP Chat API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    client: MCPAuthClient = request.app.state.auth_client
    try:
        return await client.login(payload)
    except MCPAuthError as exc:
        if _is_unauthorized_error(str(exc)):
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/mcp/tools")
async def mcp_tools(request: Request) -> dict[str, object]:
    token = _extract_mcp_token(request)
    settings = request.app.state.settings
    client = RemoteMCPClient(settings, access_token=token)
    try:
        tools = await client.list_tools()
    except MCPClientError as exc:
        if _is_unauthorized_error(str(exc)):
            raise HTTPException(status_code=401, detail=f"MCP tools/list failed: {exc}") from exc
        raise HTTPException(status_code=502, detail=f"MCP tools/list failed: {exc}") from exc
    finally:
        await client.aclose()
    return {"tools": tools}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request_data: ChatRequest, request: Request) -> ChatResponse:
    token = _extract_mcp_token(request)
    settings = request.app.state.settings
    siliconflow_client: SiliconFlowClient = request.app.state.siliconflow_client
    mcp_client = RemoteMCPClient(settings, access_token=token)
    orchestrator = ChatOrchestrator(
        siliconflow_client=siliconflow_client,
        mcp_client=mcp_client,
        default_model=settings.siliconflow_model,
    )
    try:
        return await orchestrator.run_chat(request_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        if _is_unauthorized_error(str(exc)):
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await mcp_client.aclose()
