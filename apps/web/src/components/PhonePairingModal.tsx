import {
  CheckCircle2Icon,
  CopyIcon,
  LoaderCircleIcon,
  PhoneIcon,
  RefreshCwIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiRequest, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button, Drawer, Input, SelectField, Spinner, toast } from "./ui";

type PairingState = {
  accountPublicId: string;
  code: string;
  status: string;
  expiresAt?: string;
};
type ProxyOption = { id: string; label: string };
const isPaired = (status: string) =>
  ["connected", "online", "paired", "linked_offline", "online_idle"].includes(
    status.toLowerCase(),
  );

function unpackPairing(payload: unknown): PairingState {
  const root = (payload as { data?: unknown })?.data ?? payload;
  const data = root as Record<string, unknown>;
  const account = (data.account || {}) as Record<string, unknown>;
  return {
    accountPublicId: String(
      data.accountPublicId ||
        data.account_public_id ||
        account.publicId ||
        account.public_id ||
        account.id ||
        "",
    ),
    code: String(data.pairingCode || data.pairing_code || data.code || ""),
    status: String(data.status || account.status || "pairing"),
    expiresAt: String(data.expiresAt || data.expires_at || ""),
  };
}

export function PairingCode({
  code,
  status,
  expiresAt,
}: {
  code: string;
  status: string;
  expiresAt?: string;
}) {
  const groups = useMemo(
    () => code.replace(/[^A-Za-z0-9]/g, "").match(/.{1,4}/g) || [code],
    [code],
  );
  const connected = isPaired(status);
  return (
    <section className={`pairing-code ${connected ? "connected" : ""}`}>
      {connected ? <CheckCircle2Icon size={31} /> : <PhoneIcon size={27} />}
      <span>{connected ? "账号配对成功" : "在 WhatsApp 中输入配对码"}</span>
      {!connected ? (
        <div className="code-groups">
          {groups.map((group, index) => (
            <strong key={`${group}-${index}`}>{group}</strong>
          ))}
        </div>
      ) : null}
      <small>
        {connected
          ? "会话凭证已安全保存，可以关闭窗口。"
          : expiresAt
            ? `配对码有效期至 ${new Date(expiresAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
            : "请尽快完成配对，过期后可重新生成。"}
      </small>
      {!connected && code ? (
        <Button
          variant="outline"
          onClick={() =>
            void navigator.clipboard
              .writeText(code)
              .then(() => toast.success("配对码已复制"))
          }
        >
          <CopyIcon size={15} />
          复制配对码
        </Button>
      ) : null}
    </section>
  );
}

export function PhonePairingModal({
  open,
  onClose,
  onPaired,
}: {
  open: boolean;
  onClose: () => void;
  onPaired: () => void;
}) {
  const { user } = useAuth();
  const [countryCode, setCountryCode] = useState("86");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [pairing, setPairing] = useState<PairingState | null>(null);
  const [proxies, setProxies] = useState<ProxyOption[]>([]);
  const [proxyPublicId, setProxyPublicId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      setPairing(null);
      setPhoneNumber("");
      setProxyPublicId("");
      setError("");
      setPending(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !user?.isAdmin) {
      setProxies([]);
      setProxyPublicId("");
      return;
    }
    void apiRequest("/api/ip-proxies?enabled=true&pageSize=100")
      .then((payload) => {
        const options = unwrapList<Record<string, unknown>>(payload)
          .rows.filter((row) => row.enabled !== false)
          .map((row) => ({
            id: String(row.publicId || row.id || ""),
            label: `${String(row.name || "IP 代理")}${row.countryCode ? ` · ${String(row.countryCode)}` : ""}`,
          }));
        setProxies(options);
        setProxyPublicId((current) =>
          options.some((option) => option.id === current) ? current : "",
        );
      })
      .catch(() => setProxies([]));
  }, [open, user?.isAdmin]);

  useEffect(() => {
    if (!open || !pairing?.accountPublicId || isPaired(pairing.status)) return;
    const timer = window.setInterval(() => {
      void apiRequest(`/api/personal-accounts/${pairing.accountPublicId}`)
        .then((payload) => {
          const next = unpackPairing(payload);
          setPairing((current) => ({
            ...current!,
            ...next,
            code: next.code || current!.code,
          }));
          if (isPaired(next.status)) onPaired();
        })
        .catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [onPaired, open, pairing?.accountPublicId, pairing?.status]);

  async function requestCode() {
    const prefix = countryCode.replace(/\D/g, "");
    const number = phoneNumber.replace(/\D/g, "");
    if (!prefix || !number) return;
    setPending(true);
    setError("");
    try {
      let accountId = pairing?.accountPublicId || "";
      if (!accountId) {
        const created = await apiRequest("/api/personal-accounts", {
          method: "POST",
          body: JSON.stringify({
            name: `+${prefix}${number}`,
            phone: `+${prefix}${number}`,
            proxyPublicId: user?.isAdmin
              ? proxyPublicId || undefined
              : undefined,
          }),
        });
        const createdData = ((created as { data?: Record<string, unknown> })
          .data || {}) as Record<string, unknown>;
        const account = (createdData.account || createdData) as Record<
          string,
          unknown
        >;
        accountId = String(
          account.publicId || account.public_id || account.id || "",
        );
      }
      if (!accountId)
        throw new Error("账号创建成功，但未返回 Account Public ID");
      const payload = await apiRequest(
        `/api/personal-accounts/${accountId}/pairing-code`,
        {
          method: "POST",
          body: JSON.stringify({ phone: `+${prefix}${number}` }),
        },
      );
      const next = { ...unpackPairing(payload), accountPublicId: accountId };
      if (!next.code && !isPaired(next.status))
        throw new Error("网关暂未返回配对码，请稍后重试");
      setPairing(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成配对码失败");
    } finally {
      setPending(false);
    }
  }

  const connected = Boolean(pairing && isPaired(pairing.status));
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="链接个人账号"
      description="输入 WhatsApp 号码并选择隔离代理，系统会生成手机端可用的配对码。"
      footer={
        <>
          {pairing && !connected ? (
            <Button
              variant="outline"
              onClick={() => void requestCode()}
              disabled={pending}
            >
              <RefreshCwIcon size={16} />
              重新生成
            </Button>
          ) : null}
          <Button variant={connected ? "default" : "outline"} onClick={onClose}>
            {connected ? "完成" : "关闭"}
          </Button>
        </>
      }
    >
      {!pairing ? (
        <>
          <div className="phone-fields">
            <label className="field country-code-field">
              <span>国家区号</span>
              <div className="prefix-input">
                <span>+</span>
                <Input
                  value={countryCode}
                  inputMode="numeric"
                  onChange={(event) => setCountryCode(event.target.value)}
                  placeholder="86"
                />
              </div>
            </label>
            <label className="field">
              <span>手机号码</span>
              <Input
                value={phoneNumber}
                inputMode="tel"
                onChange={(event) => setPhoneNumber(event.target.value)}
                placeholder="请输入不含区号的号码"
              />
            </label>
          </div>
          <label className="field">
            <span>账号隔离代理</span>
            {user?.isAdmin ? (
              <SelectField
                ariaLabel="账号隔离代理"
                className="w-full"
                value={proxyPublicId}
                onValueChange={setProxyPublicId}
                placeholder="系统自动分配隔离 IP"
                clearable
                options={proxies.map((proxy) => ({
                  value: proxy.id,
                  label: proxy.label,
                }))}
              />
            ) : (
              <Input disabled value="系统自动分配隔离 IP" />
            )}
          </label>
          <div className="pair-help">
            <strong>手机端操作路径</strong>
            <span>
              WhatsApp → 设置 → 已关联设备 → 关联设备 →
              改用手机号码关联。系统会先分配隔离
              IP，再创建并持久化账号会话；管理员也可以显式指定可见代理。
            </span>
          </div>
          {error ? (
            <div className="form-error" role="alert">
              {error}
            </div>
          ) : null}
          <Button
            className="full-button"
            onClick={() => void requestCode()}
            disabled={pending || !countryCode.trim() || !phoneNumber.trim()}
          >
            {pending ? (
              <LoaderCircleIcon className="spin" size={17} />
            ) : (
              <PhoneIcon size={17} />
            )}
            生成配对码
          </Button>
        </>
      ) : (
        <>
          <PairingCode
            code={pairing.code}
            status={pairing.status}
            expiresAt={pairing.expiresAt}
          />
          {!connected ? (
            <div className="pairing-poll">
              <Spinner />
              正在等待手机端完成配对…
            </div>
          ) : null}
          {error ? (
            <div className="form-error" role="alert">
              {error}
            </div>
          ) : null}
        </>
      )}
    </Drawer>
  );
}
