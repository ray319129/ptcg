// 登入 / 註冊畫面。登入後資料綁定帳號、長期保存。
import { useState } from "react";
import { login, register } from "../api/endpoints";
import { ApiError } from "../api/http";
import { useApp } from "../store";
import "./auth.css";

export function AuthScreen() {
  const doLogin = useApp((s) => s.login);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = username.trim().length >= 2 && password.length >= 4;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const fn = mode === "login" ? login : register;
      const res = await fn(username.trim(), password);
      doLogin(res.user_id, res.username);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失敗，請稍後再試");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-root">
      <div className="auth-card surface">
        <div className="auth-logo">卡匣</div>
        <div className="auth-sub">Pokemon 卡片資產管理</div>

        <div className="auth-tabs">
          <button
            className={mode === "login" ? "on" : ""}
            onClick={() => setMode("login")}
          >
            登入
          </button>
          <button
            className={mode === "register" ? "on" : ""}
            onClick={() => setMode("register")}
          >
            註冊
          </button>
        </div>

        <input
          className="auth-input"
          placeholder="帳號"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          className="auth-input"
          placeholder="密碼（至少 4 碼）"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSubmit && !busy) void submit();
          }}
        />

        {error && <div className="auth-error">{error}</div>}

        <button
          className="btn-gold auth-submit"
          disabled={!canSubmit || busy}
          onClick={submit}
        >
          {busy ? "處理中…" : mode === "login" ? "登入" : "建立帳號"}
        </button>

        <div className="auth-hint">
          資料會綁定此帳號保存，換裝置或重啟也不會遺失。
        </div>
      </div>
    </div>
  );
}
