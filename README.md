# DeepSea OUC MCP Chat

A full-stack web chat app built with Python + React.

- Backend: FastAPI
- Frontend: React + Vite
- LLM: SiliconFlow Chat Completions API
- Tool calling: MCP server via JSON-RPC over HTTP

## 1) Configure backend

```bash
cd /Users/xander/studypace/pyproject/DeapSeaOUCWEB/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at least:

```env
SILICONFLOW_API_KEY=your_real_key
```

`MCP_SERVER_URL` is already set to:

```env
http://100.68.129.231:8000/mcp
```

`MCP_LOGIN_URL` default:

```env
http://100.68.129.231:8000/login
```

Start backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 2) Start frontend

```bash
cd /Users/xander/studypace/pyproject/DeapSeaOUCWEB/frontend
npm install
cp .env.example .env
npm run dev
```

Open:

- [http://localhost:5173](http://localhost:5173)

If your backend is not on `http://127.0.0.1:8000`, set:

```bash
VITE_API_BASE_URL=http://your_backend_host:8000 npm run dev
```

## API endpoints

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/mcp/tools`
- `POST /api/chat`

## Chat request body example

```json
{
  "messages": [
    {"role": "user", "content": "What tools do you have?"}
  ],
  "model": "Qwen/Qwen3-8B",
  "temperature": 0.7,
  "max_tokens": 1024,
  "max_steps": 5,
  "use_mcp": true
}
```

When the model emits `tool_calls`, backend will invoke MCP `tools/call`, append results as `tool` messages, and then continue inference to generate final answer.

## Login and token flow

- Frontend calls `POST /api/auth/login` with:
  - `{"username":"2125","password":"123456"}`
- Backend forwards to MCP `/login`, returns:
  - `access_token`, `user_id`, `expires_in=7200`, `expires_at`
- Frontend stores token in `localStorage` and auto-removes after 2 hours.
- Frontend sends `Authorization: Bearer <access_token>` on `/api/chat` and `/api/mcp/tools`.
- If no token (or token invalid), backend returns `401`, frontend shows login page.
