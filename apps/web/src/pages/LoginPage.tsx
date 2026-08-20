import { ArrowLeftIcon, KeyRoundIcon, ShieldCheckIcon } from "lucide-react";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  Button,
  Input,
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
  Spinner,
} from "../components/ui";
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
  const { user, loading, login, verifyMfaLogin } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [security, setSecurity] = useState<LoginSecurity | null>(null);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [captchaGeneration, setCaptchaGeneration] = useState(0);
  const [mfaChallenge, setMfaChallenge] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);

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

  async function submitCredentials(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setPending(true);
    setError("");
    try {
      const result = await login(username.trim(), password, turnstileToken || undefined);
      if (result.mfaRequired) {
        setMfaChallenge(result.challengeToken);
        setMfaCode("");
        setUseRecoveryCode(false);
      } else {
        navigate("/promotion/templates", { replace: true });
      }
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

  async function submitMfa(event: FormEvent) {
    event.preventDefault();
    if (!mfaChallenge || !mfaCode.trim()) return;
    setPending(true);
    setError("");
    try {
      await verifyMfaLogin(mfaChallenge, mfaCode.trim());
      navigate("/promotion/templates", { replace: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "验证失败，请重新输入");
      setMfaCode("");
    } finally {
      setPending(false);
    }
  }

  function returnToPassword() {
    setMfaChallenge("");
    setMfaCode("");
    setUseRecoveryCode(false);
    setError("");
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <header className="login-header">
          <div className="login-logo">
            <img src="/brand/parloq-icon.svg" alt="Parloq" />
          </div>
          <h1>Parloq</h1>
          <p>
            {mfaChallenge
              ? "请完成二步验证以继续登录。"
              : "登录后管理推广模板、统一账号池与营销任务。"}
          </p>
        </header>
        {mfaChallenge ? (
          <form className="login-form" onSubmit={submitMfa}>
            <div className="flex flex-col items-center gap-2 text-center">
              <div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
                <ShieldCheckIcon size={20} />
              </div>
              <strong>{useRecoveryCode ? "使用恢复码" : "输入 6 位验证码"}</strong>
              <span className="text-sm text-muted-foreground">
                {useRecoveryCode
                  ? "输入开启二步验证时保存的一枚恢复码。"
                  : "打开身份验证器，输入当前显示的连续 6 位数字。"}
              </span>
            </div>
            {useRecoveryCode ? (
              <label className="field">
                <span>恢复码</span>
                <Input
                  autoFocus
                  autoComplete="one-time-code"
                  value={mfaCode}
                  placeholder="XXXXX-XXXXX-XXXXX-XXXXX"
                  onChange={(event) => setMfaCode(event.target.value.toUpperCase())}
                />
              </label>
            ) : (
              <div className="flex justify-center">
                <InputOTP
                  autoFocus
                  autoComplete="one-time-code"
                  maxLength={6}
                  pattern={REGEXP_ONLY_DIGITS}
                  value={mfaCode}
                  onChange={setMfaCode}
                >
                  <InputOTPGroup>
                    {Array.from({ length: 6 }, (_, index) => (
                      <InputOTPSlot key={index} index={index} className="size-10 text-base" />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              </div>
            )}
            {error ? <div className="form-error" role="alert">{error}</div> : null}
            <Button
              type="submit"
              disabled={pending || (useRecoveryCode ? mfaCode.trim().length < 20 : mfaCode.length !== 6)}
            >
              {pending ? <Spinner /> : <ShieldCheckIcon size={17} />}
              验证并登录
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setUseRecoveryCode((value) => !value);
                setMfaCode("");
                setError("");
              }}
            >
              {useRecoveryCode ? "使用 6 位验证码" : "改用恢复码"}
            </Button>
            <Button type="button" variant="ghost" onClick={returnToPassword}>
              <ArrowLeftIcon size={16} />
              返回密码登录
            </Button>
          </form>
        ) : (
        <form className="login-form" onSubmit={submitCredentials}>
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
        )}
      </section>
    </main>
  );
}
