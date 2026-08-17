import { KeyRoundIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button, Input, Spinner } from "../components/ui";
import { Turnstile } from "../components/Turnstile";
import { apiRequest, type ApiEnvelope } from "../api/client";

type LoginSecurity = {
  turnstileEnabled: boolean;
  turnstileRequired: boolean;
  turnstileSiteKey: string;
  locked: boolean;
  retryAfterSeconds: number;
};

export function LoginPage() {
  const navigate = useNavigate();
  const { user, loading, login } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [security, setSecurity] = useState<LoginSecurity | null>(null);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [captchaGeneration, setCaptchaGeneration] = useState(0);

  useEffect(() => {
    if (!loading && user) navigate("/promotion/templates", { replace: true });
  }, [loading, navigate, user]);

  async function refreshSecurity(value: string) {
    try {
      const response = await apiRequest<ApiEnvelope<LoginSecurity>>(
        `/api/auth/security?username=${encodeURIComponent(value.trim())}`,
      );
      setSecurity(response.data);
    } catch {
      setSecurity(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void refreshSecurity(username), 250);
    return () => window.clearTimeout(timer);
  }, [username]);

  useEffect(() => {
    if (!security?.locked || security.retryAfterSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setSecurity((current) =>
        current?.locked
          ? {
              ...current,
              retryAfterSeconds: Math.max(current.retryAfterSeconds - 1, 0),
            }
          : current,
      );
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [security?.locked]);

  useEffect(() => {
    if (security?.locked && security.retryAfterSeconds === 0) {
      void refreshSecurity(username);
    }
  }, [security?.locked, security?.retryAfterSeconds, username]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setPending(true);
    setError("");
    try {
      await login(username.trim(), password, turnstileToken || undefined);
      navigate("/promotion/templates", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "登录失败，请稍后重试",
      );
      setTurnstileToken("");
      setCaptchaGeneration((value) => value + 1);
      await refreshSecurity(username);
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <header className="login-header">
          <div className="login-logo">
            <img src="/brand/parloq-icon.svg" alt="Parloq" />
          </div>
          <h1>Parloq</h1>
          <p>登录后管理推广模板、统一账号池与营销任务。</p>
        </header>
        <form className="login-form" onSubmit={submit}>
          <label className="field">
            <span>用户名</span>
            <Input
              autoFocus
              autoComplete="username"
              value={username}
              placeholder="请输入用户名"
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          {security?.turnstileEnabled && security.turnstileRequired && security.turnstileSiteKey ? (
            <Turnstile
              key={captchaGeneration}
              siteKey={security.turnstileSiteKey}
              onChange={setTurnstileToken}
            />
          ) : null}
          <label className="field">
            <span>密码</span>
            <Input
              type="password"
              autoComplete="current-password"
              value={password}
              placeholder="请输入密码"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {security?.locked ? (
            <div className="form-error" role="alert">
              登录保护已触发，请在 {security.retryAfterSeconds} 秒后重试
            </div>
          ) : error ? (
            <div className="form-error" role="alert">
              {error}
            </div>
          ) : null}
          <Button
            type="submit"
            disabled={
              pending ||
              !username.trim() ||
              !password ||
              Boolean(security?.locked) ||
              Boolean(security?.turnstileRequired && !turnstileToken)
            }
          >
            {pending ? <Spinner /> : <KeyRoundIcon size={17} />}登录
          </Button>
        </form>
      </section>
    </main>
  );
}
