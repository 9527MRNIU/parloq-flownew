import {
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
} from "../components/list-page";
import {
  EntityPrimaryCell,
  type EntityStatusMeta,
} from "../components/entity-primary-cell";
import { DrawerFieldLabel } from "../components/drawer-form";
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
  id: string;
  readKey: string;
  name: string;
  shortDomain?: string;
  enabled?: boolean;
  status?: string;
  linkCount?: number;
  groupGuid?: string;
  tokenMasked?: string;
};

type DirectShortLink = {
  id: string;
  readKey: string;
  title?: string;
  shortUrl: string;
  targetUrl: string;
  enabled: boolean;
  status: string;
  providerAccountId: string;
  providerAccountName?: string;
  clickCount?: number;
  createdAt?: string;
};

function normalizeAccount(input: unknown): BitlyAccount {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "bitly-account", `${String(row.name || row.label || "")}:${String(row.createdAt || row.created_at || "")}`),
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
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "direct-short-link", `${String(row.shortUrl || row.short_url || "")}:${String(row.createdAt || row.created_at || "")}`),
    title: String(row.title || ""),
    shortUrl: String(row.shortUrl || row.short_url || ""),
    targetUrl: String(row.targetUrl || row.target_url || ""),
    enabled: Boolean(row.enabled ?? true),
    status: String(
      row.status || (row.enabled === false ? "disabled" : "active"),
    ),
    providerAccountId: snowflakeId(row, "providerAccountId", "provider_account_id"),
    providerAccountName: String(
      row.providerAccountName || row.provider_account_name || "",
    ),
    clickCount: Number(row.clickCount ?? row.click_count ?? 0),
    createdAt: String(row.createdAt || row.created_at || ""),
  };
}

function linkStatus(row: DirectShortLink): EntityStatusMeta {
  if (!row.enabled || row.status === "disabled")
    return {
      label: "已停用",
      description: "短链接已停用，不应继续用于新流量。",
      tone: "warning",
    };
  if (["failed", "invalid", "error"].includes(row.status))
    return {
      label: "异常",
      description: "短链接服务返回异常，请检查账号授权或目标地址。",
      tone: "danger",
    };
  return {
    label: "正常",
    description: "短链接可以正常访问并统计点击数据。",
    tone: "success",
  };
}

export function DirectShortLinksPage() {
  const { user, can } = useAuth();
  const canManage = can("marketing.direct_short_links.manage");
  const [accounts, setAccounts] = useState<BitlyAccount[]>([]);
  const [rows, setRows] = useState<DirectShortLink[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
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
    params.set("page", String(page));
    params.set("pageSize", String(pageSize));
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
  }, [accountId, page, pageSize, query]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);
  useEffect(() => {
    void loadLinks();
  }, [loadLinks]);
  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (page > totalPages) setPage(totalPages);
  }, [page, pageSize, total]);

  const selectedAccount = useMemo(
    () => accounts.find((row) => row.id === accountId),
    [accountId, accounts],
  );
  const accountPagination = useClientPagination(accounts, {
    resetKey: String(accountDrawer),
  });

  function openCreate() {
    setEditing(null);
    setTitle("");
    setTargetUrl("");
    setProviderAccountId(accountId);
    setDialogOpen(true);
  }

  function openEdit(row: DirectShortLink) {
    if (!row.id) return;
    setEditing(row);
    setTitle(row.title || "");
    setTargetUrl(row.targetUrl);
    setProviderAccountId(String(row.providerAccountId || ""));
    setDialogOpen(true);
  }

  async function save() {
    if (!targetUrl.trim() || (editing && !editing.id)) return;
    setPending(true);
    try {
      const body = {
        title: title.trim() || undefined,
        targetUrl: targetUrl.trim(),
        providerAccountId: providerAccountId || undefined,
      };
      if (editing)
        await apiRequest(
          `/api/direct-short-links/${editing.id}`,
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

  async function remove(row: DirectShortLink) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除短链“${row.title || row.shortUrl}”？`,
        description: "只删除本系统记录，Bitly 上已创建的短链不会被删除。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/direct-short-links/${row.id}`, {
        method: "DELETE",
      });
      await loadLinks();
      toast.success("直接短链已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  function openAccount(row?: BitlyAccount) {
    if (row && !row.id) return;
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
    if (!accountForm.name.trim() || !accountForm.shortDomain.trim() || (editingAccount && !editingAccount.id)) return;
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
          ? `/api/bitly-accounts/${editingAccount.id}`
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

  async function removeAccount(row: BitlyAccount) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除 Bitly 账号“${row.name}”？`,
        description: "该账号及其本地短链记录会一并删除；Bitly 上的账号和短链不受影响。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/bitly-accounts/${row.id}`, {
        method: "DELETE",
      });
      await loadAccounts();
      toast.success("Bitly 账号已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除账号失败");
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
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索标题、Bitly 短链或目标地址",
          onSubmit: () => {
            setPage(1);
            setQuery(keyword.trim());
          },
        }}
        filters={
          user?.isAdmin && canManage ? (
            <SelectField
              ariaLabel="Bitly 账号筛选"
              value={accountId || "__all__"}
              onValueChange={(value) => {
                setPage(1);
                setAccountId(value === "__all__" ? "" : value);
              }}
              options={[
                { value: "__all__", label: "全部 Bitly 账号" },
                ...accounts.filter((account) => account.id).map((account) => ({
                  value: account.id,
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

      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPage(1);
          setPageSize(value);
        }}
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
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <TableHead>Bitly 短链接</TableHead>
                  <TableHead adaptive>目标地址</TableHead>
                  <TableHead>账号</TableHead>
                  <TableHead>点击数</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.readKey}>
                    <TableCell>
                      <EntityPrimaryCell
                        title={row.title || row.shortUrl || "Bitly 短链"}
                        id={row.id}
                        description={row.shortUrl || "创建中"}
                        status={{
                          ...linkStatus(row),
                          details: [
                            { label: "服务账号", value: row.providerAccountName || "-" },
                            { label: "点击数", value: (row.clickCount || 0).toLocaleString() },
                          ],
                        }}
                      />
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
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.createdAt)}
                    </TableCell>
                    <TableCell>
                      <div className="flex min-w-max items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => window.open(row.shortUrl, "_blank")}
                        >
                          打开
                        </Button>
                        {canManage ? (
                          <>
                            <Button variant="outline" size="sm" disabled={!row.id} onClick={() => openEdit(row)}>
                              编辑
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              disabled={!row.id}
                              onClick={() => void remove(row)}
                            >
                              删除
                            </Button>
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
            description="创建后将直接获得 Bitly 短链接，不使用本站域名。"
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
            <DrawerFieldLabel required>目标地址</DrawerFieldLabel>
            <Input
              value={targetUrl}
              onChange={(event) => setTargetUrl(event.target.value)}
              placeholder="https://example.com/promotion"
            />
          </label>
          <label className="field">
            <DrawerFieldLabel>内部标题</DrawerFieldLabel>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="例如：8 月新品投放"
            />
          </label>
          {user?.isAdmin ? (
            <label className="field">
              <DrawerFieldLabel>Bitly 账号</DrawerFieldLabel>
              <SelectField
                value={providerAccountId || "__auto__"}
                onValueChange={(value) =>
                  setProviderAccountId(value === "__auto__" ? "" : value)
                }
                options={[
                  { value: "__auto__", label: "自动选择可用账号" },
                  ...accounts
                    .filter((row) => row.enabled && row.id)
                    .map((account) => ({
                      value: account.id,
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
              Bitly → 原始目标地址。
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
              <DrawerFieldLabel required>账号名称</DrawerFieldLabel>
              <Input
                value={accountForm.name}
                onChange={(event) =>
                  setAccountForm({ ...accountForm, name: event.target.value })
                }
              />
            </label>
            <div className="form-grid">
              <label className="field">
                <DrawerFieldLabel required>短域名</DrawerFieldLabel>
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
                <DrawerFieldLabel>Group GUID</DrawerFieldLabel>
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
              <DrawerFieldLabel required={!editingAccount}>
                Access Token{editingAccount ? "（留空不修改）" : ""}
              </DrawerFieldLabel>
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
          <ListPagination
            page={accountPagination.page}
            pageSize={accountPagination.pageSize}
            total={accountPagination.total}
            onPageChange={accountPagination.setPage}
            onPageSizeChange={accountPagination.setPageSize}
            ariaLabel="Bitly 账号池分页"
          />
          {accounts.length ? (
            <div className="pixel-list">
              {accountPagination.rows.map((row) => (
                <div key={row.readKey}>
                  <div>
                    <strong>{row.name}</strong>
                    <span>{row.id || "等待 ID 迁移"}</span>
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
                    disabled={!row.id}
                    onClick={() => openAccount(row)}
                  >
                    编辑
                  </Button>
                  <IconButton
                    label="删除 Bitly 账号"
                    variant="ghost"
                    className="danger"
                    disabled={!row.id}
                    onClick={() => void removeAccount(row)}
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
