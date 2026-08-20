import {
  CheckCircle2Icon,
  ClipboardIcon,
  KeyRoundIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  ShieldOffIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { useCallback, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { apiRequest, type ApiEnvelope } from "../api/client";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  confirmAction,
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  Input,
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
  Spinner,
  toast,
} from "../components/ui";

type MfaStatus = {
  enabled: boolean;
  enabledAt?: string | null;
  recoveryCodesRemaining: number;
  pendingSetup: boolean;
};

type MfaSetup = {
  secret: string;
  otpauthUri: string;
};

function TotpInput({
  value,
  onChange,
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <InputOTP
      autoFocus={autoFocus}
      autoComplete="one-time-code"
      maxLength={6}
      pattern={REGEXP_ONLY_DIGITS}
      value={value}
      onChange={onChange}
    >
      <InputOTPGroup>
        {Array.from({ length: 6 }, (_, index) => (
          <InputOTPSlot key={index} index={index} className="size-10 text-base" />
        ))}
      </InputOTPGroup>
    </InputOTP>
  );
}

function RecoveryCodes({
  codes,
  onDone,
}: {
  codes: string[];
  onDone: () => void;
}) {
  async function copyCodes() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast.success("恢复码已复制");
    } catch {
      toast.error("复制失败，请手动保存恢复码");
    }
  }

  return (
    <Card className="border-amber-500/30 bg-amber-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TriangleAlertIcon className="size-5 text-amber-600" />
          立即保存恢复码
        </CardTitle>
        <CardDescription>
          每枚恢复码只能使用一次。关闭本页后系统不会再次显示这些明文恢复码。
        </CardDescription>
        <CardAction>
          <Button type="button" variant="outline" size="sm" onClick={() => void copyCodes()}>
            <ClipboardIcon />
            复制全部
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 rounded-lg border bg-background p-4 font-mono text-sm sm:grid-cols-2">
          {codes.map((code) => (
            <code key={code} className="select-all text-center tracking-wide">
              {code}
            </code>
          ))}
        </div>
        <Button type="button" onClick={onDone}>
          <CheckCircle2Icon />
          我已妥善保存
        </Button>
      </CardContent>
    </Card>
  );
}

export function AccountSecurityPage() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [pendingAction, setPendingAction] = useState("");

  const [setupPassword, setSetupPassword] = useState("");
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [setupCode, setSetupCode] = useState("");
  const [setupError, setSetupError] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  const [rotatePassword, setRotatePassword] = useState("");
  const [rotateCode, setRotateCode] = useState("");
  const [rotateError, setRotateError] = useState("");
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableError, setDisableError] = useState("");

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const response = await apiRequest<ApiEnvelope<MfaStatus>>("/api/auth/mfa/status");
      setStatus(response.data);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : "加载安全设置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  async function startSetup() {
    if (!setupPassword) return;
    setPendingAction("setup");
    setSetupError("");
    try {
      const response = await apiRequest<ApiEnvelope<MfaSetup>>("/api/auth/mfa/setup", {
        method: "POST",
        body: JSON.stringify({ currentPassword: setupPassword }),
      });
      setSetup(response.data);
      setSetupCode("");
      setSetupPassword("");
    } catch (caught) {
      setSetupError(caught instanceof Error ? caught.message : "开始设置失败");
    } finally {
      setPendingAction("");
    }
  }

  async function confirmSetup() {
    if (setupCode.length !== 6) return;
    setPendingAction("confirm");
    setSetupError("");
    try {
      const response = await apiRequest<ApiEnvelope<{ recoveryCodes: string[] }>>(
        "/api/auth/mfa/setup/confirm",
        { method: "POST", body: JSON.stringify({ code: setupCode }) },
      );
      setRecoveryCodes(response.data.recoveryCodes);
      setSetup(null);
      setSetupCode("");
      await loadStatus();
      toast.success("二步验证已开启");
    } catch (caught) {
      setSetupError(caught instanceof Error ? caught.message : "验证码确认失败");
      setSetupCode("");
    } finally {
      setPendingAction("");
    }
  }

  async function regenerateCodes() {
    if (!rotatePassword || rotateCode.length !== 6) return;
    setPendingAction("rotate");
    setRotateError("");
    try {
      const response = await apiRequest<ApiEnvelope<{ recoveryCodes: string[] }>>(
        "/api/auth/mfa/recovery-codes",
        {
          method: "POST",
          body: JSON.stringify({ currentPassword: rotatePassword, code: rotateCode }),
        },
      );
      setRecoveryCodes(response.data.recoveryCodes);
      setRotatePassword("");
      setRotateCode("");
      await loadStatus();
      toast.success("恢复码已重新生成，旧恢复码已失效");
    } catch (caught) {
      setRotateError(caught instanceof Error ? caught.message : "重新生成失败");
      setRotateCode("");
    } finally {
      setPendingAction("");
    }
  }

  async function disableMfa() {
    if (!disablePassword || disableCode.length !== 6) return;
    const confirmed = await confirmAction({
      title: "关闭二步验证？",
      description: "关闭后仅需用户名和密码即可登录，其他已登录会话会被撤销。",
      confirmText: "确认关闭",
      destructive: true,
    });
    if (!confirmed) return;
    setPendingAction("disable");
    setDisableError("");
    try {
      await apiRequest("/api/auth/mfa/disable", {
        method: "POST",
        body: JSON.stringify({ currentPassword: disablePassword, code: disableCode }),
      });
      setDisablePassword("");
      setDisableCode("");
      setRecoveryCodes([]);
      await loadStatus();
      toast.success("二步验证已关闭");
    } catch (caught) {
      setDisableError(caught instanceof Error ? caught.message : "关闭失败");
      setDisableCode("");
    } finally {
      setPendingAction("");
    }
  }

  async function copySecret() {
    if (!setup) return;
    try {
      await navigator.clipboard.writeText(setup.secret);
      toast.success("密钥已复制");
    } catch {
      toast.error("复制失败，请手动复制密钥");
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
      {loading ? (
        <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Spinner /> 正在加载安全设置…
        </div>
      ) : loadError || !status ? (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>安全设置加载失败</AlertTitle>
          <AlertDescription>{loadError || "请稍后重试"}</AlertDescription>
        </Alert>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {status.enabled ? <ShieldCheckIcon className="text-emerald-600" /> : <ShieldOffIcon />}
                身份验证器
              </CardTitle>
              <CardDescription>
                支持 Google Authenticator、Microsoft Authenticator、1Password 等标准 TOTP 应用。
              </CardDescription>
              <CardAction>
                <Badge tone={status.enabled ? "success" : "neutral"}>
                  {status.enabled ? "已开启" : "未开启"}
                </Badge>
              </CardAction>
            </CardHeader>
            <CardContent>
              {status.enabled ? (
                <Alert>
                  <CheckCircle2Icon />
                  <AlertTitle>登录保护已生效</AlertTitle>
                  <AlertDescription>
                    当前还有 {status.recoveryCodesRemaining} 枚未使用恢复码。请勿将验证器或恢复码共享给他人。
                  </AlertDescription>
                </Alert>
              ) : setup ? (
                <FieldGroup>
                  <div className="grid gap-5 md:grid-cols-[180px_1fr] md:items-center">
                    <div className="flex justify-center rounded-xl bg-white p-4">
                      <QRCodeSVG value={setup.otpauthUri} size={152} level="M" />
                    </div>
                    <div className="space-y-4">
                      <div>
                        <strong className="text-sm">1. 扫描二维码</strong>
                        <p className="mt-1 text-sm text-muted-foreground">
                          在身份验证器中添加账户并扫描二维码。无法扫码时可手动输入密钥。
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 p-3">
                        <code className="min-w-0 flex-1 break-all font-mono text-sm tracking-wider">
                          {setup.secret.match(/.{1,4}/g)?.join(" ")}
                        </code>
                        <Button type="button" variant="outline" size="sm" onClick={() => void copySecret()}>
                          <ClipboardIcon />
                          复制
                        </Button>
                      </div>
                    </div>
                  </div>
                  <Field data-invalid={Boolean(setupError)}>
                    <FieldLabel>2. 输入验证器显示的 6 位验证码</FieldLabel>
                    <TotpInput value={setupCode} onChange={setSetupCode} autoFocus />
                    <FieldDescription>验证成功后才会正式开启二步验证。</FieldDescription>
                    <FieldError>{setupError}</FieldError>
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      onClick={() => void confirmSetup()}
                      disabled={pendingAction === "confirm" || setupCode.length !== 6}
                    >
                      {pendingAction === "confirm" ? <Spinner /> : <ShieldCheckIcon />}
                      验证并开启
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setSetup(null);
                        setSetupCode("");
                        setSetupError("");
                      }}
                      disabled={Boolean(pendingAction)}
                    >
                      取消
                    </Button>
                  </div>
                </FieldGroup>
              ) : (
                <FieldGroup>
                  <Alert>
                    <KeyRoundIcon />
                    <AlertTitle>开启前需要验证当前密码</AlertTitle>
                    <AlertDescription>
                      系统不会强制任何角色开启。启用后可随时使用密码和动态验证码关闭。
                    </AlertDescription>
                  </Alert>
                  <Field data-invalid={Boolean(setupError)}>
                    <FieldLabel htmlFor="mfa-setup-password">当前密码</FieldLabel>
                    <Input
                      id="mfa-setup-password"
                      type="password"
                      autoComplete="current-password"
                      value={setupPassword}
                      onChange={(event) => setSetupPassword(event.target.value)}
                    />
                    <FieldError>{setupError}</FieldError>
                  </Field>
                  <div>
                    <Button
                      type="button"
                      onClick={() => void startSetup()}
                      disabled={pendingAction === "setup" || !setupPassword}
                    >
                      {pendingAction === "setup" ? <Spinner /> : <ShieldCheckIcon />}
                      开始设置
                    </Button>
                  </div>
                </FieldGroup>
              )}
            </CardContent>
          </Card>

          {recoveryCodes.length ? (
            <RecoveryCodes codes={recoveryCodes} onDone={() => setRecoveryCodes([])} />
          ) : null}

          {status.enabled && !recoveryCodes.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>重新生成恢复码</CardTitle>
                  <CardDescription>新恢复码生成后，所有旧恢复码立即失效。</CardDescription>
                </CardHeader>
                <CardContent>
                  <FieldGroup>
                    <Field data-invalid={Boolean(rotateError)}>
                      <FieldLabel htmlFor="mfa-rotate-password">当前密码</FieldLabel>
                      <Input
                        id="mfa-rotate-password"
                        type="password"
                        autoComplete="current-password"
                        value={rotatePassword}
                        onChange={(event) => setRotatePassword(event.target.value)}
                      />
                    </Field>
                    <Field data-invalid={Boolean(rotateError)}>
                      <FieldLabel>6 位验证码</FieldLabel>
                      <TotpInput value={rotateCode} onChange={setRotateCode} />
                      <FieldError>{rotateError}</FieldError>
                    </Field>
                    <div>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void regenerateCodes()}
                        disabled={
                          pendingAction === "rotate" || !rotatePassword || rotateCode.length !== 6
                        }
                      >
                        {pendingAction === "rotate" ? <Spinner /> : <RefreshCwIcon />}
                        重新生成
                      </Button>
                    </div>
                  </FieldGroup>
                </CardContent>
              </Card>

              <Card className="border-destructive/30">
                <CardHeader>
                  <CardTitle>关闭二步验证</CardTitle>
                  <CardDescription>关闭后，其他已登录会话将被撤销。</CardDescription>
                </CardHeader>
                <CardContent>
                  <FieldGroup>
                    <Field data-invalid={Boolean(disableError)}>
                      <FieldLabel htmlFor="mfa-disable-password">当前密码</FieldLabel>
                      <Input
                        id="mfa-disable-password"
                        type="password"
                        autoComplete="current-password"
                        value={disablePassword}
                        onChange={(event) => setDisablePassword(event.target.value)}
                      />
                    </Field>
                    <Field data-invalid={Boolean(disableError)}>
                      <FieldLabel>6 位验证码</FieldLabel>
                      <TotpInput value={disableCode} onChange={setDisableCode} />
                      <FieldError>{disableError}</FieldError>
                    </Field>
                    <div>
                      <Button
                        type="button"
                        variant="destructive"
                        onClick={() => void disableMfa()}
                        disabled={
                          pendingAction === "disable" ||
                          !disablePassword ||
                          disableCode.length !== 6
                        }
                      >
                        {pendingAction === "disable" ? <Spinner /> : <ShieldOffIcon />}
                        关闭二步验证
                      </Button>
                    </div>
                  </FieldGroup>
                </CardContent>
              </Card>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
