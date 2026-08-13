import { KeyRoundIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button, Input, Spinner } from "../components/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const { user, loading, login } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && user) navigate("/promotion/templates", { replace: true });
  }, [loading, navigate, user]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setPending(true);
    setError("");
    try {
      await login(username.trim(), password);
      navigate("/promotion/templates", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "登录失败，请稍后重试",
      );
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
          {error ? (
            <div className="form-error" role="alert">
              {error}
            </div>
          ) : null}
          <Button
            type="submit"
            disabled={pending || !username.trim() || !password}
          >
            {pending ? <Spinner /> : <KeyRoundIcon size={17} />}登录
          </Button>
        </form>
      </section>
    </main>
  );
}
