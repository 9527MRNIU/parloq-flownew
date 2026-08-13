import {
  CopyIcon,
  ExternalLinkIcon,
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  EmptyState,
  IconButton,
  Input,
  SelectField,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  toast,
} from "../components/ui";

type BitlyAccount = {
  id: string | number;
  publicId?: string;
  name: string;
  shortDomain?: string;
  enabled?: boolean;
  status?: string;
  linkCount?: number;
  groupGuid?: string;
  tokenMasked?: string;
};

type DirectShortLink = {
  id: string | number;
  publicId?: string;
  title?: string;
  shortUrl: string;
  targetUrl: string;
  enabled: boolean;
  status: string;
  providerAccountId?: string | number;
  providerAccountName?: string;
  clickCount?: number;
  createdAt?: string;
};

function normalizeAccount(input: unknown): BitlyAccount {
  const row = input as Record<string, unknown>;
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    publicId: String(row.publicId || row.public_id || row.id || ""),
    name: String(row.name || row.label || "Bitly 账号"),
    shortDomain: String(row.shortDomain || row.short_domain || "bit.ly"),
    enabled: Boolean(row.enabled ?? true),
    status: String(row.status || "active"),
    linkCount: Number(row.linkCount ?? row.link_count ?? 0),
    groupGuid: String(row.groupGuid || row.group_guid || ""),
    tokenMasked: String(
      row.tokenMasked ||
        row.token_masked ||
        row.accessTokenMasked ||
        row.access_token_masked ||
        "",
    ),
  };
}

function normalizeLink(input: unknown): DirectShortLink {
  const row = input as Record<string, unknown>;
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    publicId: String(row.publicId || row.public_id || row.id || ""),
    title: String(row.title || ""),
    shortUrl: String(row.shortUrl || row.short_url || ""),
    targetUrl: String(row.targetUrl || row.target_url || ""),
    enabled: Boolean(row.enabled ?? true),
    status: String(
      row.status || (row.enabled === false ? "disabled" : "active"),
    ),
    providerAccountId: (row.providerAccountId || row.provider_account_id) as
      string | number | undefined,
    providerAccountName: String(
      row.providerAccountName || row.provider_account_name || "",
    ),
    clickCount: Number(row.clickCount ?? row.click_count ?? 0),
    createdAt: String(row.createdAt || row.created_at || ""),
  };
}

function stateBadge(row: DirectShortLink) {
  if (!row.enabled || row.status === "disabled")
    return <Badge tone="warning">已停用</Badge>;
  if (["failed", "invalid", "error"].includes(row.status))
    return <Badge tone="danger">异常</Badge>;
  return <Badge tone="success">正常</Badge>;
}

export function DirectShortLinksPage() {
  const { user, can } = useAuth();
  const canManage = can("marketing.direct_short_links.manage");
  const [accounts, setAccounts] = useState<BitlyAccount[]>([]);
  const [rows, setRows] = useState<DirectShortLink[]>([]);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [accountId, setAccountId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DirectShortLink | null>(null);
  const [title, setTitle] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [providerAccountId, setProviderAccountId] = useState("");
  const [pending, setPending] = useState(false);
  const [accountDrawer, setAccountDrawer] = useState(false);
  const [editingAccount, setEditingAccount] = useState<BitlyAccount | null>(
    null,
  );
  const [accountPending, setAccountPending] = useState(false);
  const [accountForm, setAccountForm] = useState({
    name: "",
    accessToken: "",
    groupGuid: "",
    shortDomain: "bit.ly",
    enabled: true,
  });

  const loadAccounts = useCallback(async () => {
    if (!user?.isAdmin) {
      setAccounts([]);
      return;
    }
    try {
      const payload = await apiRequest("/api/direct-short-links/accounts");
      const list = unwrapList<unknown>(payload);
      setAccounts(list.rows.map(normalizeAccount));
    } catch {
      setAccounts([]);
    }
  }, [user?.isAdmin]);

  const loadLinks = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (query) params.set("keyword", query);
    if (accountId) params.set("providerAccountId", accountId);
    params.set("page", "1");
    params.set("pageSize", "100");
    try {
      const payload = await apiRequest(`/api/direct-short-links?${params}`);
      const list = unwrapList<unknown>(payload);
      setRows(list.rows.map(normalizeLink));
      setTotal(list.total);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载直接短链失败");
    } finally {
      setLoading(false);
    }
  }, [accountId, query]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);
  useEffect(() => {
    void loadLinks();
  }, [loadLinks]);

  const selectedAccount = useMemo(
    () => accounts.find((row) => String(row.publicId || row.id) === accountId),
    [accountId, accounts],
  );

  function openCreate() {
    setEditing(null);
    setTitle("");
    setTargetUrl("");
    setProviderAccountId(accountId);
    setDialogOpen(true);
  }

  function openEdit(row: DirectShortLink) {
    setEditing(row);
    setTitle(row.title || "");
    setTargetUrl(row.targetUrl);
    setProviderAccountId(String(row.providerAccountId || ""));
    setDialogOpen(true);
  }

  async function save() {
    if (!targetUrl.trim()) return;
    setPending(true);
    try {
      const body = {
        title: title.trim() || undefined,
        targetUrl: targetUrl.trim(),
        providerAccountId: providerAccountId || undefined,
      };
      if (editing)
        await apiRequest(
          `/api/direct-short-links/${editing.publicId || editing.id}`,
          { method: "PATCH", body: JSON.stringify(body) },
        );
      else
        await apiRequest("/api/direct-short-links", {
          method: "POST",
          body: JSON.stringify(body),
        });
      setDialogOpen(false);
      await Promise.all([loadLinks(), loadAccounts()]);
      toast.success(editing ? "直接短链已更新" : "直接短链已创建");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function archive(row: DirectShortLink) {
    if (
      !(await confirmAction({
        title: `归档短链“${row.title || row.shortUrl}”？`,
        description: "归档后该短链将不再出现在当前列表中。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`/api/direct-short-links/${row.publicId || row.id}`, {
        method: "DELETE",
      });
      await loadLinks();
      toast.success("直接短链已归档");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档失败");
    }
  }

  function openAccount(row?: BitlyAccount) {
    setEditingAccount(row || null);
    setAccountForm(
      row
        ? {
            name: row.name,
            accessToken: "",
            groupGuid: row.groupGuid || "",
            shortDomain: row.shortDomain || "bit.ly",
            enabled: row.enabled ?? true,
          }
        : {
            name: "",
            accessToken: "",
            groupGuid: "",
            shortDomain: "bit.ly",
            enabled: true,
          },
    );
    setAccountDrawer(true);
  }

  async function saveAccount() {
    if (!accountForm.name.trim() || !accountForm.shortDomain.trim()) return;
    setAccountPending(true);
    try {
      const body = {
        name: accountForm.name.trim(),
        shortDomain: accountForm.shortDomain.trim(),
        groupGuid: accountForm.groupGuid.trim() || undefined,
        accessToken: accountForm.accessToken.trim() || undefined,
        enabled: accountForm.enabled,
      };
      await apiRequest(
        editingAccount
          ? `/api/bitly-accounts/${editingAccount.publicId || editingAccount.id}`
          : "/api/bitly-accounts",
        {
          method: editingAccount ? "PATCH" : "POST",
          body: JSON.stringify(body),
        },
      );
      setEditingAccount(null);
      setAccountForm({
        name: "",
        accessToken: "",
        groupGuid: "",
        shortDomain: "bit.ly",
        enabled: true,
      });
      await loadAccounts();
      toast.success(editingAccount ? "Bitly 账号已更新" : "Bitly 账号已添加");
    } catch (caught) {
      toast.error(
        caught instanceof Error ? caught.message : "保存 Bitly 账号失败",
      );
    } finally {
      setAccountPending(false);
    }
  }

  async function archiveAccount(row: BitlyAccount) {
    if (
      !(await confirmAction({
        title: `归档 Bitly 账号“${row.name}”？`,
        description: "归档后该账号不会再用于创建直接短链。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`/api/bitly-accounts/${row.publicId || row.id}`, {
        method: "DELETE",
      });
      await loadAccounts();
      toast.success("Bitly 账号已归档");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档账号失败");
    }
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("短链已复制");
    } catch {
      toast.error("复制失败，请手动复制");
    }
  }

  return (
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索标题、Bitly 短链或目标地址",
          onSubmit: () => setQuery(keyword.trim()),
        }}
        filters={
          user?.isAdmin && canManage ? (
            <SelectField
              ariaLabel="Bitly 账号筛选"
              value={accountId || "__all__"}
              onValueChange={(value) =>
                setAccountId(value === "__all__" ? "" : value)
              }
              options={[
                { value: "__all__", label: "全部 Bitly 账号" },
                ...accounts.map((account) => ({
                  value: String(account.publicId || account.id),
                  label: account.name,
                })),
              ]}
            />
          ) : null
        }
        meta={`${total} 条短链${selectedAccount ? ` · ${selectedAccount.name}` : ""}`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void Promise.all([loadLinks(), loadAccounts()])}
              disabled={loading}
            >
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
            {user?.isAdmin ? (
              <Button variant="outline" onClick={() => openAccount()}>
                <KeyRoundIcon size={17} />
                Bitly 账号
              </Button>
            ) : null}
            {canManage ? (
              <Button
                onClick={openCreate}
                disabled={Boolean(
                  user?.isAdmin &&
                  accounts.length > 0 &&
                  !accounts.some((row) => row.enabled),
                )}
              >
                <PlusIcon size={17} />
                创建直接短链
              </Button>
            ) : null}
          </>
        }
      />

      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
            正在加载直接短链…
          </div>
        ) : error ? (
          <div className="error-state">
            <strong>加载失败</strong>
            <span>{error}</span>
            <Button variant="outline" onClick={() => void loadLinks()}>
              重试
            </Button>
          </div>
        ) : rows.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Bitly 短链接</TableHead>
                  <TableHead>目标地址</TableHead>
                  <TableHead>账号</TableHead>
                  <TableHead>点击数</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.publicId || row.id}>
                    <TableCell>
                      <div className="cell-main">
                        <strong>
                          {row.title || row.shortUrl || "Bitly 短链"}
                        </strong>
                        <span className="inline-link">
                          <a
                            href={row.shortUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {row.shortUrl || "创建中"}
                          </a>
                          {row.shortUrl ? (
                            <IconButton
                              label="复制"
                              className="mini-icon"
                              onClick={() => void copy(row.shortUrl)}
                            >
                              <CopyIcon size={14} />
                            </IconButton>
                          ) : null}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="truncate-cell" title={row.targetUrl}>
                        {row.targetUrl}
                      </div>
                    </TableCell>
                    <TableCell>
                      {row.providerAccountName ||
                        accounts.find(
                          (item) =>
                            String(item.id) === String(row.providerAccountId),
                        )?.name ||
                        "-"}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {(row.clickCount || 0).toLocaleString()}
                    </TableCell>
                    <TableCell>{stateBadge(row)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.createdAt)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <IconButton
                          label="打开"
                          onClick={() => window.open(row.shortUrl, "_blank")}
                        >
                          <ExternalLinkIcon size={16} />
                        </IconButton>
                        {canManage ? (
                          <>
                            <IconButton label="编辑" onClick={() => openEdit(row)}>
                              <PencilIcon size={16} />
                            </IconButton>
                            <IconButton
                              label="归档"
                              variant="ghost"
                              className="danger"
                              onClick={() => void archive(row)}
                            >
                              <Trash2Icon size={16} />
                            </IconButton>
                          </>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title="暂无直接短链"
            description="创建后将直接获得 Bitly 短链接，不经过本站域名或跳转网关。"
          />
        )}
      </ListTableCard>

      <Drawer
        open={dialogOpen}
        onClose={() => !pending && setDialogOpen(false)}
        title={editing ? "编辑直接短链" : "创建直接短链"}
        description={
          editing
            ? "更新 Bitly 短链的标题和目标地址。"
            : "系统将从可用账号池创建真实 Bitly 短链接。"
        }
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={pending}
            >
              取消
            </Button>
            <Button
              onClick={() => void save()}
              disabled={pending || !targetUrl.trim()}
            >
              {pending ? (
                <LoaderCircleIcon className="spin" size={17} />
              ) : (
                <Link2Icon size={17} />
              )}
              {editing ? "保存修改" : "创建 Bitly 短链"}
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <span>目标地址</span>
            <Input
              value={targetUrl}
              onChange={(event) => setTargetUrl(event.target.value)}
              placeholder="https://example.com/promotion"
            />
          </label>
          <label className="field">
            <span>内部标题（可选）</span>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：8 月新品投放"
            />
          </label>
          {user?.isAdmin ? (
            <label className="field">
              <span>Bitly 账号</span>
              <SelectField
                value={providerAccountId || "__auto__"}
                onValueChange={(value) =>
                  setProviderAccountId(value === "__auto__" ? "" : value)
                }
                options={[
                  { value: "__auto__", label: "自动选择可用账号" },
                  ...accounts
                    .filter((row) => row.enabled)
                    .map((account) => ({
                      value: String(account.publicId || account.id),
                      label: `${account.name} · ${account.shortDomain || "bit.ly"}`,
                    })),
                ]}
              />
            </label>
          ) : (
            <div className="system-note">
              <KeyRoundIcon size={18} />
              <div>
                <strong>系统自动选择 Bitly 账号</strong>
                <span>账号凭证与账号池由管理员统一维护。</span>
              </div>
            </div>
          )}
          <div className="route-preview">
            <span>跳转链路</span>
            <strong>
              <Link2Icon size={16} /> Bitly 短链
            </strong>
            <small>
              Bitly → 原始目标地址。不会创建本站短链或经过本站网关。
            </small>
          </div>
        </div>
      </Drawer>
      <Drawer
        open={accountDrawer}
        onClose={() => !accountPending && setAccountDrawer(false)}
        title="Bitly 账号管理"
        description="Access Token 只加密保存，后续不会回显原文。"
        footer={<Button onClick={() => setAccountDrawer(false)}>完成</Button>}
      >
        <div className="drawer-form">
          <div className="pixel-create-card">
            <strong>
              {editingAccount
                ? `编辑 · ${editingAccount.name}`
                : "添加 Bitly 账号"}
            </strong>
            <label className="field">
              <span>账号名称</span>
              <Input
                value={accountForm.name}
                onChange={(event) =>
                  setAccountForm({ ...accountForm, name: event.target.value })
                }
              />
            </label>
            <div className="form-grid">
              <label className="field">
                <span>短域名</span>
                <Input
                  value={accountForm.shortDomain}
                  onChange={(event) =>
                    setAccountForm({
                      ...accountForm,
                      shortDomain: event.target.value,
                    })
                  }
                  placeholder="bit.ly"
                />
              </label>
              <label className="field">
                <span>Group GUID（可选）</span>
                <Input
                  value={accountForm.groupGuid}
                  onChange={(event) =>
                    setAccountForm({
                      ...accountForm,
                      groupGuid: event.target.value,
                    })
                  }
                  placeholder="留空自动发现"
                />
              </label>
            </div>
            <label className="field">
              <span>Access Token{editingAccount ? "（留空不修改）" : ""}</span>
              <Input
                type="password"
                autoComplete="new-password"
                value={accountForm.accessToken}
                onChange={(event) =>
                  setAccountForm({
                    ...accountForm,
                    accessToken: event.target.value,
                  })
                }
                placeholder={
                  editingAccount?.tokenMasked || "请输入 Bitly Access Token"
                }
              />
            </label>
            <label className="switch-row">
              <span>
                <strong>启用账号</strong>
                <small>停用后不会再用于创建直接短链。</small>
              </span>
              <Switch
                checked={accountForm.enabled}
                onCheckedChange={(enabled) =>
                  setAccountForm({ ...accountForm, enabled })
                }
              />
            </label>
            <div className="flex flex-wrap justify-end gap-2">
              {editingAccount ? (
                <Button variant="ghost" onClick={() => openAccount()}>
                  取消编辑
                </Button>
              ) : null}
              <Button
                disabled={
                  accountPending ||
                  !accountForm.name.trim() ||
                  !accountForm.shortDomain.trim()
                }
                onClick={() => void saveAccount()}
              >
                {accountPending ? <Spinner /> : <PlusIcon size={16} />}
                {editingAccount ? "保存账号" : "添加账号"}
              </Button>
            </div>
          </div>
          <div className="binding-list-header">
            <strong>账号池</strong>
            <span>{accounts.length}</span>
          </div>
          {accounts.length ? (
            <div className="pixel-list">
              {accounts.map((row) => (
                <div key={row.publicId || row.id}>
                  <div>
                    <strong>{row.name}</strong>
                    <span>
                      {row.shortDomain || "bit.ly"} ·{" "}
                      {row.tokenMasked || row.status || "已配置"}
                    </span>
                  </div>
                  <Badge tone={row.enabled ? "success" : "neutral"}>
                    {row.enabled ? "可用" : "停用"}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openAccount(row)}
                  >
                    编辑
                  </Button>
                  <IconButton
                    label="归档 Bitly 账号"
                    variant="ghost"
                    className="danger"
                    onClick={() => void archiveAccount(row)}
                  >
                    <Trash2Icon size={15} />
                  </IconButton>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="暂无 Bitly 账号"
              description="添加账号后即可创建直接 Bitly 短链。"
            />
          )}
        </div>
      </Drawer>
    </StandardListPage>
  );
}
