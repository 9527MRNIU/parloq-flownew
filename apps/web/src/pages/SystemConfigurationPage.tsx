import {
  BookOpenIcon,
  ExternalLinkIcon,
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
  Modal,
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
  paymentMode?: "account_balance" | "verified_card";
  paymentId?: string;
  accountId?: string;
  baseUrl?: string;
  repository?: string;
  ref?: string;
  catalogPath?: string;
};

type PlatformConfiguration = {
  key: "namesilo" | "cloudflare" | "baota" | "github";
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

const CLOUDFLARE_TOKEN_PERMISSIONS = [
  "Account → Account Settings → Read",
  "Zone → Zone → Read",
  "Zone → DNS → Edit",
  "Zone → Zone Settings → Edit",
] as const;

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
        paymentMode: settings.paymentMode === "verified_card" ? "verified_card" : "account_balance",
        paymentId: String(settings.paymentId || ""),
        accountId: String(settings.accountId || ""),
        baseUrl: String(settings.baseUrl || ""),
        repository: String(settings.repository || ""),
        ref: String(settings.ref || ""),
        catalogPath: String(settings.catalogPath || ""),
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
        paymentMode: row.settings.paymentMode || "account_balance",
        paymentId: row.settings.paymentId || "",
        accountId: row.settings.accountId || "",
        baseUrl: row.settings.baseUrl || "",
        repository: row.settings.repository || "",
        ref: row.settings.ref || "main",
        catalogPath: row.settings.catalogPath || "artifacts/catalog.json",
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
  const [cloudflareGuideOpen, setCloudflareGuideOpen] = useState(false);

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
    if (
      row.key === "namesilo"
      && draft.enabled
      && draft.paymentMode === "verified_card"
      && !draft.paymentId?.trim()
    ) {
      toast.error("使用已验证信用卡支付时必须填写 NameSilo Payment ID");
      return;
    }
    if (row.key === "baota" && draft.enabled && !draft.baseUrl?.trim()) {
      toast.error("启用宝塔面板前请填写面板地址");
      return;
    }
    if (row.key === "github" && draft.enabled && !draft.repository?.trim()) {
      toast.error("启用 GitHub 前请填写私人仓库");
      return;
    }
    setPendingKey(`${row.key}:save`);
    try {
      await apiRequest(`/api/system/configuration/${row.key}`, {
        method: "PUT",
        body: JSON.stringify({
          ...(credential ? { value: credential } : {}),
          enabled: draft.enabled,
          ...(row.key === "namesilo"
            ? {
                paymentMode: draft.paymentMode || "account_balance",
                paymentId: draft.paymentId?.trim() || "",
              }
            : {}),
          ...(row.key === "cloudflare" ? { accountId: draft.accountId?.trim() || "" } : {}),
          ...(row.key === "baota" ? { baseUrl: draft.baseUrl?.trim() || "" } : {}),
          ...(row.key === "github"
            ? {
                repository: draft.repository?.trim() || "",
                ref: draft.ref?.trim() || "main",
                catalogPath: draft.catalogPath?.trim() || "artifacts/catalog.json",
              }
            : {}),
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

                  {row.key === "github" ? (
                    <>
                      <DrawerFormField
                        label="私人仓库"
                        htmlFor="system-github-repository"
                        hint="填写 owner/repository 或完整的 GitHub HTTPS 地址。"
                      >
                        <Input
                          id="system-github-repository"
                          value={draft.repository || ""}
                          disabled={busy}
                          onChange={(event) => updateDraft(row.key, { repository: event.target.value })}
                          placeholder="zaptel099/parloq-flow-template-kit"
                          autoComplete="off"
                          spellCheck={false}
                          className="max-w-2xl"
                        />
                      </DrawerFormField>
                      <DrawerFormField
                        label="分支或标签"
                        htmlFor="system-github-ref"
                        hint="系统读取这个版本的远程模板和集成源码。"
                      >
                        <Input
                          id="system-github-ref"
                          value={draft.ref || "main"}
                          disabled={busy}
                          onChange={(event) => updateDraft(row.key, { ref: event.target.value })}
                          placeholder="main"
                          autoComplete="off"
                          spellCheck={false}
                          className="max-w-2xl"
                        />
                      </DrawerFormField>
                      <DrawerFormField
                        label="目录清单"
                        htmlFor="system-github-catalog"
                        hint="清单记录项目编号、模板或集成类型以及对应源码目录。"
                      >
                        <Input
                          id="system-github-catalog"
                          value={draft.catalogPath || "artifacts/catalog.json"}
                          disabled={busy}
                          onChange={(event) => updateDraft(row.key, { catalogPath: event.target.value })}
                          placeholder="artifacts/catalog.json"
                          autoComplete="off"
                          spellCheck={false}
                          className="max-w-2xl"
                        />
                      </DrawerFormField>
                    </>
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
                    <>
                      <DrawerFormField label="支付方式" htmlFor="system-namesilo-payment-mode">
                        <Select
                          value={draft.paymentMode || "account_balance"}
                          disabled={busy}
                          onValueChange={(paymentMode) => updateDraft(row.key, {
                            paymentMode: paymentMode as PlatformSettings["paymentMode"],
                          })}
                        >
                          <SelectTrigger id="system-namesilo-payment-mode" className="w-full max-w-2xl">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="account_balance">NameSilo 账户余额</SelectItem>
                            <SelectItem value="verified_card">已验证信用卡</SelectItem>
                          </SelectContent>
                        </Select>
                      </DrawerFormField>
                      <DrawerFormField
                        label="Payment ID"
                        htmlFor="system-namesilo-payment-id"
                        hint={draft.paymentMode === "verified_card"
                          ? "当前购买将使用这个已验证信用卡 ID。"
                          : "保留信用卡 ID 便于随时切换；余额模式不会向 NameSilo 传递该值。"}
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
                    </>
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
                      {row.key === "cloudflare" ? (
                        <Button variant="outline" onClick={() => setCloudflareGuideOpen(true)}>
                          <BookOpenIcon />
                          创建指引
                        </Button>
                      ) : null}
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

      <Modal
        open={cloudflareGuideOpen}
        title="Cloudflare API Token 创建指引"
        description="推荐创建账户 API Token，用户 API Token 也可以使用；不要填写 Global API Key 或 Token ID。"
        onClose={() => setCloudflareGuideOpen(false)}
        footer={
          <>
            <Button variant="outline" onClick={() => setCloudflareGuideOpen(false)}>关闭</Button>
            <Button asChild>
              <a href="https://dash.cloudflare.com/" target="_blank" rel="noreferrer">
                打开 Cloudflare
                <ExternalLinkIcon />
              </a>
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <section className="rounded-lg border border-border bg-muted/30 p-3">
            <h3 className="font-medium">推荐：账户 API Token</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Cloudflare 控制台 → Manage Account（管理账户）→ Account API Tokens → Create Token
            </p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              也可以使用：右上角个人头像 → My Profile → API Tokens 创建用户 API Token。
            </p>
          </section>

          <section className="grid gap-2">
            <h3 className="font-medium">创建方式</h3>
            <ol className="grid list-decimal gap-1.5 pl-5 text-sm leading-6 text-muted-foreground">
              <li>选择 Edit Zone DNS 模板。</li>
              <li>在模板已有权限基础上，增加 Zone → Zone Settings → Edit。</li>
              <li>Account Resources 选择目标账户。</li>
              <li>Zone Resources 选择该账户下的 All zones。</li>
            </ol>
          </section>

          <section className="grid gap-2">
            <h3 className="font-medium">最终权限</h3>
            <ul className="grid gap-1.5 text-sm text-muted-foreground">
              {CLOUDFLARE_TOKEN_PERMISSIONS.map((permission) => (
                <li key={permission} className="rounded-md border border-border px-3 py-2 font-mono">
                  {permission}
                </li>
              ))}
            </ul>
          </section>

          <p className="rounded-lg bg-muted/40 px-3 py-2 text-sm leading-6 text-muted-foreground">
            Client IP Address Filtering 建议首次创建时留空。Token 创建成功后只显示一次，请复制完整的 Token 值并回到本页保存、测试连接。
          </p>
        </div>
      </Modal>
    </StandardListPage>
  );
}
