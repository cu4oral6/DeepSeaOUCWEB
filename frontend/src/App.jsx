import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const AUTH_STORAGE_KEY = "deepsea_mcp_auth";
const TOKEN_TTL_MS = 2 * 60 * 60 * 1000;

const INITIAL_MESSAGES = [
  {
    role: "assistant",
    content: "Hello, I am connected to SiliconFlow + MCP.",
    localOnly: true,
  },
];

function parseAuthRecord() {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    if (
      typeof data.accessToken !== "string" ||
      !data.accessToken ||
      typeof data.userId !== "string" ||
      !data.userId ||
      typeof data.expiresAt !== "number"
    ) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      return null;
    }
    if (Date.now() >= data.expiresAt) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      return null;
    }
    return data;
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

function saveAuthRecord(auth) {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

function clearAuthRecord() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

function buildPayload(messages, input) {
  const content = input.trim();
  if (!content) return null;

  const nextMessages = [...messages, { role: "user", content }];
  const requestMessages = nextMessages
    .filter((item) => !item.localOnly)
    .filter((item) => item.role === "user" || item.role === "assistant")
    .map((item) => ({ role: item.role, content: item.content }));

  return { nextMessages, requestMessages };
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function App() {
  const [auth, setAuth] = useState(() => parseAuthRecord());
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [toolTraces, setToolTraces] = useState([]);
  const [model, setModel] = useState("Qwen/Qwen3-8B");
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState("");

  const chatCount = useMemo(() => messages.filter((m) => m.role === "user").length, [messages]);
  const expiresMinutes = useMemo(() => {
    if (!auth) return 0;
    const ms = Math.max(0, auth.expiresAt - Date.now());
    return Math.ceil(ms / 60000);
  }, [auth]);

  useEffect(() => {
    const path = auth ? "/" : "/login";
    if (window.location.pathname !== path) {
      window.history.replaceState({}, "", path);
    }
  }, [auth]);

  useEffect(() => {
    if (!auth) return undefined;
    const ms = auth.expiresAt - Date.now();
    if (ms <= 0) {
      clearAuthRecord();
      setAuth(null);
      setMessages(INITIAL_MESSAGES);
      setToolTraces([]);
      setError("");
      return undefined;
    }
    const timer = window.setTimeout(() => {
      clearAuthRecord();
      setAuth(null);
      setMessages(INITIAL_MESSAGES);
      setToolTraces([]);
      setError("登录已过期，请重新登录。");
    }, ms);
    return () => window.clearTimeout(timer);
  }, [auth]);

  function logout(reason = "") {
    clearAuthRecord();
    setAuth(null);
    setMessages(INITIAL_MESSAGES);
    setToolTraces([]);
    setInput("");
    setLoading(false);
    setError(reason);
  }

  async function handleLogin() {
    if (loginLoading) return;
    const username = loginForm.username.trim();
    const password = loginForm.password;
    if (!username || !password) {
      setLoginError("请输入账号和密码。");
      return;
    }

    setLoginLoading(true);
    setLoginError("");
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "登录失败");
      }

      const expiresAt =
        typeof data.expires_at === "number" ? data.expires_at * 1000 : Date.now() + TOKEN_TTL_MS;
      const nextAuth = {
        accessToken: data.access_token,
        userId: data.user_id,
        expiresAt,
      };
      saveAuthRecord(nextAuth);
      setAuth(nextAuth);
      setMessages(INITIAL_MESSAGES);
      setToolTraces([]);
      setError("");
    } catch (err) {
      setLoginError(err.message || String(err));
    } finally {
      setLoginLoading(false);
    }
  }

  async function sendMessage() {
    if (loading || !auth) return;

    const payload = buildPayload(messages, input);
    if (!payload) return;

    setInput("");
    setError("");
    setToolTraces([]);
    setMessages(payload.nextMessages);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${auth.accessToken}`,
        },
        body: JSON.stringify({
          messages: payload.requestMessages,
          model,
          temperature: 0.7,
          max_tokens: 1024,
          max_steps: 5,
          use_mcp: true,
        }),
      });

      const data = await response.json();
      if (response.status === 401) {
        logout("登录状态失效，请重新登录。");
        return;
      }
      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }

      setMessages((prev) => [...prev, { role: "assistant", content: data.reply || "(empty)" }]);
      setToolTraces(data.tool_traces || []);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  if (!auth) {
    return (
      <div className="auth-shell">
        <section className="auth-card">
          <h1>校园 AI 助手登录</h1>
          <p>使用教务系统的账号登录，token 本地保存 2 小时后自动失效。</p>
          <label>
            学号/账号
            <input
              value={loginForm.username}
              onChange={(e) => setLoginForm((prev) => ({ ...prev, username: e.target.value }))}
              placeholder="学号"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={loginForm.password}
              onChange={(e) => setLoginForm((prev) => ({ ...prev, password: e.target.value }))}
              placeholder="请输入密码"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleLogin();
                }
              }}
            />
          </label>
          <button onClick={handleLogin} disabled={loginLoading}>
            {loginLoading ? "登录中..." : "登录"}
          </button>
          {loginError ? <p className="error">{loginError}</p> : null}
        </section>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="topbar">
        <h1>DeepSea MCP Chat</h1>
        <p>Python + React + SiliconFlow + MCP</p>
        <div className="session-meta">
          <span>当前用户: {auth.userId}</span>
          <span>Token 剩余约 {expiresMinutes} 分钟</span>
          <button onClick={() => logout("")}>退出登录</button>
        </div>
      </header>

      <main className="layout">
        <section className="chat-panel">
          <div className="chat-header">
            <label>
              Model
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="Qwen/Qwen3-8B"
                readonly="readonly"
              />
            </label>
            <span className="counter">Turns: {chatCount}</span>
          </div>

          <div className="messages">
            {messages.map((msg, idx) => (
              <article key={`${msg.role}-${idx}`} className={`bubble ${msg.role}`}>
                <div className="role">{msg.role}</div>
                <pre>{msg.content}</pre>
              </article>
            ))}
          </div>

          <div className="composer">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything. The assistant can call MCP tools automatically."
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
            />
            <button onClick={sendMessage} disabled={loading}>
              {loading ? "Thinking..." : "Send"}
            </button>
          </div>
          {error ? <p className="error">{error}</p> : null}
        </section>

        <aside className="tool-panel">
          <h2>MCP Tool Calls</h2>
          {toolTraces.length === 0 ? (
            <p className="muted">No tool call in this turn.</p>
          ) : (
            toolTraces.map((trace, idx) => (
              <section key={`${trace.tool_name}-${idx}`} className="trace-card">
                <h3>{trace.tool_name}</h3>
                <h4>arguments</h4>
                <pre>{formatJson(trace.arguments)}</pre>
                <h4>result preview</h4>
                <pre>{trace.result_preview}</pre>
              </section>
            ))
          )}
        </aside>
      </main>
    </div>
  );
}
