import {
  LoaderCircleIcon,
  PlugZapIcon,
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiRequest, formatDateTime } from "../api/client";
import {
  Badge,
  Button,
  confirmAction,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Spinner,
  Switch,
  toast,
} from "../components/ui";
import {
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";
import { StandardListPage } from "../components/list-page";

type PlatformSettings = {
  paymentId?: string;
  accountId?: string;
  baseUrl?: string;
};

type PlatformConfiguration = {
  key: "namesilo" | "cloudflare" | "baota";
  name: string;
  credentialLabel: string;
  description: string;
  configured: boolean;
  maskedValue?: string;
  enabled: boolean;
  settings: PlatformSettings;
  lastTestStatus: "untested" | "success" | "failed";
  lastTestMessage?: string;
  lastTestAt?: string;
  updatedAt?: string;
  updatedBy?: string;
};

type PlatformDraft = PlatformSettings & {
  value: string;
  enabled: boolean;
};

type CloudflareAccount = { id: string; name: string };

function platformRows(payload: unknown): PlatformConfiguration[] {
  const body = payload as { data?: { platforms?: unknown[] } };
  return (body.data?.platforms ?? []).map((value) => {
    const row = value as Record<string, unknown>;
    const settings = (row.settings ?? {}) as Record<string, unknown>;
    return {
      key: String(row.key || "") as PlatformConfiguration["key"],
      name: String(row.name || ""),
      credentialLabel: String(row.credentialLabel || "API Token"),
      description: String(row.description || ""),
      configured: Boolean(row.configured),
      maskedValue: String(row.maskedValue || ""),
      enabled: Boolean(row.enabled),
      settings: {
        paymentId: String(settings.paymentId || ""),
        accountId: String(settings.accountId || ""),
        baseUrl: String(settings.baseUrl || ""),
      },
      lastTestStatus: String(row.lastTestStatus || "untested") as PlatformConfiguration["lastTestStatus"],
      lastTestMessage: String(row.lastTestMessage || ""),
      lastTestAt: String(row.lastTestAt || ""),
      updatedAt: String(row.updatedAt || ""),
      updatedBy: String(row.updatedBy || ""),
    };
  });
}

function draftsFromRows(rows: PlatformConfiguration[]): Record<string, PlatformDraft> {
  return Object.fromEntries(
    rows.map((row) => [
      row.key,
      {
        value: "",
        enabled: row.enabled,
        paymentId: row.settings.paymentId || "",
        accountId: row.settings.accountId || "",
        baseUrl: row.settings.baseUrl || "",
      },
    ]),
  );
}

function statusBadge(status: PlatformConfiguration["lastTestStatus"]) {
  if (status === "success") return <Badge tone="success">成功</Badge>;
  if (status === "failed") return <Badge tone="danger">失败</Badge>;
  return <Badge tone="neutral">尚未测试</Badge>;
}

export function SystemConfigurationPage() {
  const [rows, setRows] = useState<PlatformConfiguration[]>([]);
  const [drafts, setDrafts] = useState<Record<string, PlatformDraft>>({});
  const [cloudflareAccounts, setCloudflareAccounts] = useState<CloudflareAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingKey, setPendingKey] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const nextRows = platformRows(await apiRequest("/api/system/configuration"));
      setRows(nextRows);
      setDrafts(draftsFromRows(nextRows));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载系统配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function updateDraft(key: string, values: Partial<PlatformDraft>) {
    setDrafts((current) => ({
      ...current,
      [key]: { ...current[key], ...values },
    }));
  }

  async function save(row: PlatformConfiguration) {
    const draft = drafts[row.key];
    if (!draft) return;
    const credential = draft.value.trim();
    if (!row.configured && credential.length < 8) {
      toast.error(`请输入 ${row.credentialLabel}`);
      return;
    }
    if (row.key === "namesilo" && draft.paymentId && !/^\d{1,64}$/.test(draft.paymentId.trim())) {
      toast.error("NameSilo 支付 ID 只能包含数字");
      return;
    }
    if (row.key === "namesilo" && draft.enabled && !draft.paymentId?.trim()) {
      toast.error("启用 NameSilo 前必须填写信用卡 Payment ID");
      return;
    }
    if (row.key === "baota" && draft.enabled && !draft.baseUrl?.trim()) {
      toast.error("启用宝塔面板前请填写面板地址");
      return;
    }
    setPendingKey(`${row.key}:save`);
    try {
      await apiRequest(`/api/system/configuration/${row.key}`, {
        method: "PUT",
        body: JSON.stringify({
          ...(credential ? { value: credential } : {}),
          enabled: draft.enabled,
          ...(row.key === "namesilo" ? { paymentId: draft.paymentId?.trim() || "" } : {}),
          ...(row.key === "cloudflare" ? { accountId: draft.accountId?.trim() || "" } : {}),
          ...(row.key === "baota" ? { baseUrl: draft.baseUrl?.trim() || "" } : {}),
        }),
      });
      if (row.key === "cloudflare") setCloudflareAccounts([]);
      await load();
      toast.success(`${row.name} 配置已保存`);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存配置失败");
    } finally {
      setPendingKey("");
    }
  }

  async function testConnection(row: PlatformConfiguration) {
    setPendingKey(`${row.key}:test`);
    try {
      const payload = (await apiRequest(`/api/system/configuration/${row.key}/test`, {
        method: "POST",
      })) as {
        data?: {
          ok?: boolean;
          message?: string;
          accounts?: CloudflareAccount[];
        };
      };
      if (row.key === "cloudflare") {
        const accounts = payload.data?.accounts || [];
        setCloudflareAccounts(accounts);
      }
      await load();
      if (payload.data?.ok) toast.success(payload.data.message || "连接成功");
      else toast.error(payload.data?.message || "连接失败");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "连接测试失败");
    } finally {
      setPendingKey("");
    }
  }

  async function clear(row: PlatformConfiguration) {
    if (
      !(await confirmAction({
        title: `清除“${row.name}”凭据？`,
        description: "清除后平台会立即停用，依赖该凭据的自动化操作将无法执行。",
        confirmText: "确认清除",
        destructive: true,
      }))
    ) return;
    setPendingKey(`${row.key}:clear`);
    try {
      await apiRequest(`/api/system/configuration/${row.key}`, { method: "DELETE" });
      if (row.key === "cloudflare") setCloudflareAccounts([]);
      await load();
      toast.success(`${row.name} 凭据已清除`);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "清除凭据失败");
    } finally {
      setPendingKey("");
    }
  }

  const busy = Boolean(pendingKey);

  return (
    <StandardListPage>
      <div className="w-full max-w-5xl">
        {loading && !rows.length ? (
          <div className="loading-state min-h-52">
            <Spinner />
            正在加载系统配置…
          </div>
        ) : error && !rows.length ? (
          <div className="error-state min-h-52">
            <strong>加载失败</strong>
            <span>{error}</span>
            <Button variant="outline" onClick={() => void load()}>重试</Button>
          </div>
        ) : (
          <DrawerFormLayout>
            {rows.map((row) => {
              const draft = drafts[row.key] || { value: "", enabled: false };
              const inputInvalid = Boolean(draft.value.trim()) && draft.value.trim().length < 8;
              const currentAccountId = draft.accountId || row.settings.accountId || "";
              return (
                <DrawerFormSection key={row.key} title={row.name}>
                  <DrawerFormField label="凭据状态" align="start">
                    <div className="min-h-8 pt-1">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <Badge tone={row.configured ? "neutral" : "warning"}>
                          {row.configured ? "凭据已配置" : "凭据未配置"}
                        </Badge>
                        {row.maskedValue ? (
                          <span className="font-mono text-sm text-muted-foreground">{row.maskedValue}</span>
                        ) : null}
                      </div>
                      <p className="mt-1.5 text-sm leading-5 text-muted-foreground">
                        凭据留空将保留当前已保存的凭据。
                      </p>
                    </div>
                  </DrawerFormField>

                  <DrawerFormField label="启用平台">
                    <div className="flex h-8 items-center gap-3">
                      <Switch
                        checked={draft.enabled}
                        disabled={busy}
                        onCheckedChange={(enabled) => updateDraft(row.key, { enabled })}
                        aria-label={`${row.name} 启用平台`}
                      />
                      <span className="text-sm text-muted-foreground">
                        {draft.enabled ? "启用" : "停用"}
                      </span>
                    </div>
                  </DrawerFormField>

                  {row.key === "baota" ? (
                    <DrawerFormField label="面板地址" htmlFor="system-baota-base-url">
                      <Input
                        id="system-baota-base-url"
                        value={draft.baseUrl || ""}
                        disabled={busy}
                        onChange={(event) => updateDraft(row.key, { baseUrl: event.target.value })}
                        placeholder="https://panel.example.com:8888"
                        className="max-w-2xl"
                      />
                    </DrawerFormField>
                  ) : null}

                  <DrawerFormField
                    label={row.credentialLabel}
                    htmlFor={`system-credential-${row.key}`}
                    hint={row.description}
                    meta={inputInvalid ? "至少输入 8 个字符" : undefined}
                  >
                    <Input
                      id={`system-credential-${row.key}`}
                      type="password"
                      autoComplete="new-password"
                      spellCheck={false}
                      aria-invalid={inputInvalid || undefined}
                      value={draft.value}
                      disabled={busy}
                      onChange={(event) => updateDraft(row.key, { value: event.target.value })}
                      placeholder={row.configured ? "留空以保留现有凭据" : `请输入 ${row.credentialLabel}`}
                      className="max-w-2xl"
                    />
                  </DrawerFormField>

                  {row.key === "namesilo" ? (
                    <DrawerFormField
                      label="Payment ID"
                      htmlFor="system-namesilo-payment-id"
                      hint="NameSilo 中已验证、可用于 API 自动扣款的信用卡 ID。"
                    >
                      <Input
                        id="system-namesilo-payment-id"
                        inputMode="numeric"
                        autoComplete="off"
                        value={draft.paymentId || ""}
                        disabled={busy}
                        onChange={(event) => updateDraft(row.key, { paymentId: event.target.value })}
                        placeholder="输入 NameSilo Payment ID"
                        className="max-w-2xl"
                      />
                    </DrawerFormField>
                  ) : null}

                  {row.key === "cloudflare" ? (
                    <>
                      <DrawerFormField label="已保存的 Cloudflare 账户">
                        <div className="flex min-h-8 items-center font-mono text-sm text-muted-foreground">
                          {row.settings.accountId || "测试连接后自动发现"}
                        </div>
                      </DrawerFormField>
                      {cloudflareAccounts.length > 1 ? (
                        <DrawerFormField label="Cloudflare 账户" htmlFor="system-cloudflare-account">
                          <Select
                            value={currentAccountId || undefined}
                            disabled={busy}
                            onValueChange={(accountId) => updateDraft(row.key, { accountId })}
                          >
                            <SelectTrigger id="system-cloudflare-account" className="w-full max-w-2xl">
                              <SelectValue placeholder="请选择 Cloudflare 账户" />
                            </SelectTrigger>
                            <SelectContent>
                              {cloudflareAccounts.map((account) => (
                                <SelectItem key={account.id} value={account.id}>
                                  {account.name || "未命名账户"} · {account.id}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </DrawerFormField>
                      ) : null}
                    </>
                  ) : null}

                  <DrawerFormField label="连接测试" align="start">
                    <div className="min-h-8 pt-1">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        {statusBadge(row.lastTestStatus)}
                        {row.lastTestAt ? (
                          <span className="text-sm text-muted-foreground">{formatDateTime(row.lastTestAt)}</span>
                        ) : null}
                      </div>
                      {row.lastTestMessage ? (
                        <p className="mt-1.5 text-sm leading-5 text-muted-foreground">{row.lastTestMessage}</p>
                      ) : null}
                    </div>
                  </DrawerFormField>

                  <DrawerFormField label="操作">
                    <div className="flex flex-wrap items-center gap-2">
                      <Button disabled={busy || (!row.configured && draft.value.trim().length < 8)} onClick={() => void save(row)}>
                        {pendingKey === `${row.key}:save` ? <LoaderCircleIcon className="spin" /> : <SaveIcon />}
                        保存配置
                      </Button>
                      <Button variant="outline" disabled={busy || !row.configured} onClick={() => void testConnection(row)}>
                        {pendingKey === `${row.key}:test` ? <LoaderCircleIcon className="spin" /> : <PlugZapIcon />}
                        测试连接
                      </Button>
                      <Button variant="outline" disabled={busy || !row.configured} onClick={() => void clear(row)}>
                        {pendingKey === `${row.key}:clear` ? <LoaderCircleIcon className="spin" /> : <Trash2Icon />}
                        清除凭据
                      </Button>
                    </div>
                  </DrawerFormField>
                </DrawerFormSection>
              );
            })}
          </DrawerFormLayout>
        )}
      </div>
    </StandardListPage>
  );
}
