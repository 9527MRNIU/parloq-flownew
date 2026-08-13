import {
  AlertTriangleIcon,
  CheckCheckIcon,
  FolderInputIcon,
  LoaderCircleIcon,
  LogOutIcon,
  MessageSquareTextIcon,
  PowerIcon,
  RefreshCwIcon,
  UnplugIcon,
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
  Checkbox,
  confirmAction,
  EmptyState,
  IconButton,
  Input,
  Modal,
  SelectField,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
  toast,
} from "../components/ui";

type Account = {
  id: string;
  ownerId: string;
  phone: string;
  name: string;
  countryCode: string;
  status: string;
  connected: boolean;
  proxyPublicId: string;
  proxyName: string;
  source: string;
  sourceRefType: string;
  sourceRefId: string;
  importFormat: string;
  validationStatus: string;
  metadataSyncStatus: string;
  lastError: string;
  groupId: string;
  groupName: string;
  accepted: number | null;
  delivered: number | null;
  lastConnectedAt?: string;
  createdAt?: string;
};
type ProxyRow = {
  publicId: string;
  name: string;
  countryCode: string;
  enabled: boolean;
};
type AccountGroup = { id: string; name: string; ownerId: string };
const val = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
const optionalNumber = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && value !== "") {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }
  }
  return null;
};
function accountRow(input: unknown): Account {
  const row = input as Record<string, unknown>;
  const status =
    val(row, "connectionStatus", "connection_status", "status") || "offline";
  const proxy = (row.proxyBinding || row.proxy_binding || {}) as Record<
    string,
    unknown
  >;
  const group = (row.group || {}) as Record<string, unknown>;
  return {
    id: val(row, "publicId", "public_id", "id"),
    ownerId: val(row, "createdBy", "created_by"),
    phone: val(row, "phoneNumber", "phone_number", "phone"),
    name: val(row, "displayName", "display_name", "name"),
    countryCode: val(row, "countryCode", "country_code"),
    status,
    connected: Boolean(
      row.connected ??
        ["connected", "online", "online_idle", "sending"].includes(status),
    ),
    proxyPublicId:
      val(row, "proxyPublicId", "proxy_public_id") ||
      val(proxy, "proxyPublicId", "proxy_public_id"),
    proxyName:
      val(row, "proxyName", "proxy_name") ||
      val(proxy, "proxyName", "proxy_name"),
    source: val(row, "source", "credentialSource", "credential_source"),
    sourceRefType: val(row, "sourceRefType", "source_ref_type"),
    sourceRefId: val(row, "sourceRefId", "source_ref_id"),
    importFormat: val(row, "importFormat", "import_format"),
    validationStatus: val(
      row,
      "validationStatus",
      "validation_status",
    ),
    metadataSyncStatus: val(
      row,
      "metadataSyncStatus",
      "metadata_sync_status",
      "syncStatus",
      "sync_status",
    ),
    lastError: val(row, "lastError", "last_error"),
    groupId: val(group, "id", "publicId", "public_id"),
    groupName: val(group, "name"),
    accepted: optionalNumber(
      row,
      "acceptedCount",
      "accepted_count",
      "singleTickCount",
      "sentCount",
      "sent_count",
    ),
    delivered: optionalNumber(
      row,
      "deliveredCount",
      "delivered_count",
      "doubleTickCount",
    ),
    lastConnectedAt: val(row, "lastConnectedAt", "last_connected_at"),
    createdAt: val(row, "createdAt", "created_at"),
  };
}
function proxyRow(input: unknown): ProxyRow {
  const row = input as Record<string, unknown>;
  return {
    publicId: val(row, "publicId", "public_id", "id"),
    name: val(row, "name"),
    countryCode: val(row, "countryCode", "country_code"),
    enabled: Boolean(row.enabled ?? true),
  };
}
function connectionBadge(row: Account) {
  if (row.connected) return <Badge tone="success">在线</Badge>;
  if (["pairing", "connecting", "warming"].includes(row.status))
    return <Badge tone="warning">连接中</Badge>;
  if (["logged_out", "reauth_required", "revoked"].includes(row.status))
    return <Badge tone="danger">需重新配对</Badge>;
  return <Badge tone="neutral">离线</Badge>;
}
function sourceBadge(row: Account) {
  if (["landing_page", "landing", "pairing"].includes(row.source))
    return <Badge tone="primary">落地页链接</Badge>;
  if (["json", "json_import", "import"].includes(row.source))
    return <Badge tone="neutral">JSON 导入</Badge>;
  return <Badge tone="neutral">待识别</Badge>;
}
function validationBadge(status: string) {
  if (status === "ready") return <Badge tone="success">验证通过</Badge>;
  if (status === "failed") return <Badge tone="danger">验证失败</Badge>;
  if (status === "validating") return <Badge tone="warning">验证中</Badge>;
  return <Badge tone="neutral">待验证</Badge>;
}
function metadataBadge(status: string) {
  if (status === "ready" || status === "synced")
    return <Badge tone="success">已同步</Badge>;
  if (status === "failed") return <Badge tone="danger">同步失败</Badge>;
  if (status === "unsupported") return <Badge tone="neutral">不支持</Badge>;
  if (status === "syncing") return <Badge tone="warning">同步中</Badge>;
  return <Badge tone="warning">待同步</Badge>;
}
const canSwitchProxy = (row: Account) =>
  ["linked_offline", "unpaired"].includes(row.status);

export function PersonalAccountsPage() {
  const { user, can } = useAuth();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [rows, setRows] = useState<Account[]>([]);
  const [proxies, setProxies] = useState<ProxyRow[]>([]);
  const [groups, setGroups] = useState<AccountGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("all");
  const [validationFilter, setValidationFilter] = useState("all");
  const [metadataFilter, setMetadataFilter] = useState("all");
  const [groupFilter, setGroupFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [batchGroupId, setBatchGroupId] = useState("");
  const [groupingIds, setGroupingIds] = useState<string[]>([]);
  const [operation, setOperation] = useState("");
  const [testAccount, setTestAccount] = useState<Account | null>(null);
  const [testTo, setTestTo] = useState("");
  const [testText, setTestText] = useState("Parloq 连接测试消息");
  const [testPending, setTestPending] = useState(false);
  const [testResult, setTestResult] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [accountsPayload, groupsPayload, proxiesPayload] = await Promise.all([
        apiRequest("/api/personal-accounts?pageSize=100"),
        apiRequest("/api/account-groups?pageSize=100"),
        user?.isAdmin
          ? apiRequest("/api/ip-proxies?pageSize=100").catch(() => null)
          : Promise.resolve(null),
      ]);
      const nextRows = unwrapList<unknown>(accountsPayload).rows.map(accountRow);
      setRows(nextRows);
      setSelectedIds((current) =>
        current.filter((id) => nextRows.some((row) => row.id === id)),
      );
      setGroups(
        unwrapList<Record<string, unknown>>(groupsPayload)
          .rows.map((row) => ({
            id: val(row, "publicId", "public_id", "id"),
            name: val(row, "name"),
            ownerId: val(row, "createdBy", "created_by"),
          }))
          .filter((row) => row.id),
      );
      if (proxiesPayload) {
        setProxies(unwrapList<unknown>(proxiesPayload).rows.map(proxyRow));
      } else setProxies([]);
    } catch (caught) {
      setRows([]);
      setGroups([]);
      toast.error(caught instanceof Error ? caught.message : "账号加载失败");
    } finally {
      setLoading(false);
    }
  }, [user?.isAdmin]);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter(
      (row) =>
        (!search ||
          `${row.phone} ${row.name} ${row.countryCode} ${row.groupName} ${row.sourceRefType} ${row.sourceRefId} ${row.importFormat} ${row.lastError}`
            .toLowerCase()
            .includes(search)) &&
        (status === "all" ||
          (status === "online"
            ? row.connected
            : status === "offline"
              ? !row.connected
              : row.status === status)) &&
        (validationFilter === "all" ||
          row.validationStatus === validationFilter) &&
        (metadataFilter === "all" ||
          row.metadataSyncStatus === metadataFilter) &&
        (sourceFilter === "all" || row.source === sourceFilter) &&
        (groupFilter === "all" ||
          (groupFilter === "__ungrouped__"
            ? !row.groupId
            : row.groupId === groupFilter)),
    );
  }, [
    groupFilter,
    keyword,
    metadataFilter,
    rows,
    sourceFilter,
    status,
    validationFilter,
  ]);
  const visibleIds = visible.map((row) => row.id);
  const allVisibleSelected =
    Boolean(visibleIds.length) &&
    visibleIds.every((id) => selectedIds.includes(id));
  const selectedOwnerIds = new Set(
    rows
      .filter((row) => selectedIds.includes(row.id))
      .map((row) => row.ownerId),
  );
  const batchGroups = groups.filter(
    (group) =>
      selectedOwnerIds.size === 1 && selectedOwnerIds.has(group.ownerId),
  );
  const batchTargetValid =
    batchGroupId === "__ungrouped__" ||
    batchGroups.some((group) => group.id === batchGroupId);
  async function action(
    row: Account,
    name: "connect" | "disconnect" | "logout",
  ) {
    if (
      name === "logout" &&
      !(await confirmAction({
        title: `登出 ${row.phone}？`,
        description: "登出后需要重新配对设备，会话凭证将被清除。",
        confirmText: "确认登出",
      }))
    )
      return;
    setOperation(`${row.id}:${name}`);
    try {
      await apiRequest(`/api/personal-accounts/${row.id}/${name}`, {
        method: "POST",
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setOperation("");
    }
  }
  async function bindProxy(row: Account, proxyPublicId: string) {
    try {
      await apiRequest(`/api/personal-accounts/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ proxyPublicId: proxyPublicId || null }),
      });
      await load();
      toast.success("隔离代理已更新");
    } catch (caught) {
      toast.error(
        caught instanceof Error
          ? caught.message
          : "代理绑定失败；在线账号请先断开连接",
      );
    }
  }
  async function changeGroup(row: Account, groupId: string) {
    setGroupingIds((current) => [...current, row.id]);
    try {
      await apiRequest(`/api/personal-accounts/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ groupId: groupId || null }),
      });
      await load();
      toast.success(groupId ? "账号分组已更新" : "账号已移出分组");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "账号改组失败");
    } finally {
      setGroupingIds((current) => current.filter((id) => id !== row.id));
    }
  }
  async function batchChangeGroup() {
    if (!selectedIds.length || !batchGroupId || !batchTargetValid) return;
    const groupId = batchGroupId === "__ungrouped__" ? null : batchGroupId;
    const targetIds = [...selectedIds];
    setGroupingIds((current) => [...new Set([...current, ...targetIds])]);
    const results = await Promise.allSettled(
      targetIds.map((id) =>
        apiRequest(`/api/personal-accounts/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ groupId }),
        }),
      ),
    );
    const failed = results.filter((result) => result.status === "rejected");
    setGroupingIds((current) =>
      current.filter((id) => !targetIds.includes(id)),
    );
    await load();
    if (failed.length) {
      toast.warning(
        `批量改组完成：成功 ${targetIds.length - failed.length} 个，失败 ${failed.length} 个`,
      );
    } else {
      toast.success(`已更新 ${targetIds.length} 个账号的分组`);
      setSelectedIds([]);
    }
  }
  async function sendTest() {
    if (!testAccount || !testTo.trim() || !testText.trim()) return;
    setTestPending(true);
    setTestResult("");
    try {
      const payload = await apiRequest(
        `/api/personal-accounts/${testAccount.id}/send`,
        {
          method: "POST",
          body: JSON.stringify({
            to: testTo.trim(),
            message: testText.trim(),
            idempotencyKey: crypto.randomUUID(),
          }),
        },
      );
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        {}) as Record<string, unknown>;
      const delivery = (data.messageDelivery ||
        data.message_delivery ||
        data) as Record<string, unknown>;
      setTestResult(
        val(delivery, "deliveryStatus", "status") || "server_accepted",
      );
    } catch (caught) {
      setTestResult(caught instanceof Error ? caught.message : "发送失败");
    } finally {
      setTestPending(false);
    }
  }
  return (
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索号码、名称或国家",
        }}
        filters={
          <>
            <SelectField
              ariaLabel="在线状态"
              className="w-[145px]"
              value={status}
              onValueChange={setStatus}
              options={[
                { value: "all", label: "全部在线状态" },
                { value: "online", label: "在线" },
                { value: "offline", label: "离线" },
                { value: "reauth_required", label: "需重新配对" },
              ]}
            />
            <SelectField
              ariaLabel="凭据验证状态"
              className="w-[145px]"
              value={validationFilter}
              onValueChange={setValidationFilter}
              options={[
                { value: "all", label: "全部验证状态" },
                { value: "pending", label: "待验证" },
                { value: "validating", label: "验证中" },
                { value: "ready", label: "验证通过" },
                { value: "failed", label: "验证失败" },
              ]}
            />
            <SelectField
              ariaLabel="资料同步状态"
              className="w-[145px]"
              value={metadataFilter}
              onValueChange={setMetadataFilter}
              options={[
                { value: "all", label: "全部同步状态" },
                { value: "pending", label: "待同步" },
                { value: "syncing", label: "同步中" },
                { value: "ready", label: "已同步" },
                { value: "failed", label: "同步失败" },
                { value: "unsupported", label: "不支持" },
              ]}
            />
            <SelectField
              ariaLabel="账号来源"
              className="w-[145px]"
              value={sourceFilter}
              onValueChange={setSourceFilter}
              options={[
                { value: "all", label: "全部来源" },
                { value: "landing_page", label: "落地页链接" },
                { value: "json_import", label: "JSON 导入" },
              ]}
            />
            <SelectField
              ariaLabel="账号分组筛选"
              className="w-[155px]"
              value={groupFilter}
              onValueChange={setGroupFilter}
              options={[
                { value: "all", label: "全部分组" },
                { value: "__ungrouped__", label: "未分组" },
                ...groups.map((group) => ({
                  value: group.id,
                  label: user?.isAdmin
                    ? `${group.name} · 客户 #${group.ownerId}`
                    : group.name,
                })),
              ]}
            />
          </>
        }
        meta={
          selectedIds.length
            ? `已选择 ${selectedIds.length} / ${visible.length} 个账号`
            : `${visible.length} 个账号`
        }
        actions={
          <>
            {canManage && selectedIds.length ? (
              <>
                <SelectField
                  ariaLabel="批量设置账号分组"
                  className="w-[170px]"
                  value={batchGroupId}
                  onValueChange={setBatchGroupId}
                  placeholder="选择目标分组"
                  options={[
                    { value: "__ungrouped__", label: "移出所有分组" },
                    ...batchGroups.map((group) => ({
                      value: group.id,
                      label: user?.isAdmin
                        ? `${group.name} · 客户 #${group.ownerId}`
                        : group.name,
                    })),
                  ]}
                />
                <Button
                  variant="outline"
                  disabled={
                    !batchGroupId ||
                    !batchTargetValid ||
                    Boolean(groupingIds.length)
                  }
                  onClick={() => void batchChangeGroup()}
                >
                  {groupingIds.length ? <Spinner /> : <FolderInputIcon size={16} />}
                  批量改组
                </Button>
              </>
            ) : null}
            <Button
              variant="outline"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
          </>
        }
      />
      <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
            正在加载统一账号池…
          </div>
        ) : visible.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    aria-label="选择全部可见账号"
                    checked={allVisibleSelected}
                    disabled={!canManage}
                    onCheckedChange={(checked) =>
                      setSelectedIds((current) =>
                        checked
                          ? Array.from(new Set([...current, ...visibleIds]))
                          : current.filter((id) => !visibleIds.includes(id)),
                      )
                    }
                  />
                </TableHead>
                <TableHead>账号</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>验证 / 资料</TableHead>
                <TableHead>分组</TableHead>
                <TableHead>连接</TableHead>
                <TableHead>固定代理</TableHead>
                <TableHead>发送结果</TableHead>
                <TableHead>异常 / 最近连接</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <Checkbox
                      aria-label={`选择账号 ${row.phone || row.name || row.id}`}
                      checked={selectedIds.includes(row.id)}
                      disabled={!canManage}
                      onCheckedChange={(checked) =>
                        setSelectedIds((current) =>
                          checked
                            ? [...new Set([...current, row.id])]
                            : current.filter((id) => id !== row.id),
                        )
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      <strong>{row.name || row.phone || row.id}</strong>
                      <span>
                        {row.phone || row.id}
                        {row.countryCode ? ` · ${row.countryCode}` : ""}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main">
                      {sourceBadge(row)}
                      <span
                        className="max-w-48 truncate"
                        title={[row.sourceRefType, row.sourceRefId, row.importFormat]
                          .filter(Boolean)
                          .join(" · ")}
                      >
                        {[row.sourceRefType, row.sourceRefId, row.importFormat]
                          .filter(Boolean)
                          .join(" · ") || "暂无来源详情"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main items-start">
                      {validationBadge(row.validationStatus)}
                      {metadataBadge(row.metadataSyncStatus)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <SelectField
                      ariaLabel={`账号 ${row.phone || row.id} 的分组`}
                      className="w-[165px]"
                      value={row.groupId}
                      onValueChange={(groupId) =>
                        void changeGroup(row, groupId)
                      }
                      placeholder="未分组"
                      clearable
                      disabled={
                        !canManage || groupingIds.includes(row.id)
                      }
                      options={groups
                        .filter((group) => group.ownerId === row.ownerId)
                        .map((group) => ({
                          value: group.id,
                          label: group.name,
                        }))}
                    />
                  </TableCell>
                  <TableCell>{connectionBadge(row)}</TableCell>
                  <TableCell>
                    {user?.isAdmin ? (
                      <div className="cell-main">
                        <SelectField
                          ariaLabel="固定隔离代理"
                          className="w-[210px]"
                          value={row.proxyPublicId}
                          onValueChange={(value) => void bindProxy(row, value)}
                          placeholder="系统自动分配"
                          clearable
                          disabled={!canManage || !canSwitchProxy(row) || Boolean(operation)}
                          options={proxies
                            .filter((proxy) => proxy.enabled)
                            .map((proxy) => ({
                              value: proxy.publicId,
                              label: `${proxy.name}${proxy.countryCode ? ` · ${proxy.countryCode}` : ""}`,
                            }))}
                        />
                        {!canSwitchProxy(row) ? (
                          <span>先断开账号再切换代理</span>
                        ) : null}
                      </div>
                    ) : (
                      <div className="cell-main">
                        <strong>
                          {row.proxyName || "系统自动分配隔离 IP"}
                        </strong>
                        <span>隔离代理由系统维护</span>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="tick-stats">
                      <span>
                        <CheckCheckIcon size={14} />
                        单勾 {row.accepted == null ? "-" : row.accepted}
                      </span>
                      <span>
                        <CheckCheckIcon size={14} />
                        双勾 {row.delivered == null ? "-" : row.delivered}
                      </span>
                      {row.accepted == null && row.delivered == null ? (
                        <small className="text-muted-foreground">待同步</small>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main max-w-64">
                      {row.lastError ? (
                        <span
                          className="flex items-center gap-1 truncate text-destructive"
                          title={row.lastError}
                        >
                          <AlertTriangleIcon size={13} />
                          {row.lastError}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">无异常</span>
                      )}
                      <span>最近连接 {formatDateTime(row.lastConnectedAt)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {canManage ? <div className="flex items-center justify-end gap-1">
                      {row.connected ? (
                        <IconButton
                          label="断开"
                          disabled={Boolean(operation)}
                          onClick={() => void action(row, "disconnect")}
                        >
                          <UnplugIcon size={16} />
                        </IconButton>
                      ) : (
                        <IconButton
                          label="连接"
                          disabled={Boolean(operation)}
                          onClick={() => void action(row, "connect")}
                        >
                          <PowerIcon size={16} />
                        </IconButton>
                      )}
                      <IconButton
                        label="发测试消息"
                        disabled={!row.connected}
                        onClick={() => {
                          setTestAccount(row);
                          setTestTo("");
                          setTestResult("");
                        }}
                      >
                        <MessageSquareTextIcon size={16} />
                      </IconButton>
                      <IconButton
                        label="登出并解绑设备"
                        className="text-destructive"
                        disabled={Boolean(operation)}
                        onClick={() => void action(row, "logout")}
                      >
                        {operation === `${row.id}:logout` ? (
                          <LoaderCircleIcon className="spin" size={16} />
                        ) : (
                          <LogOutIcon size={16} />
                        )}
                      </IconButton>
                    </div> : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="还没有账号"
            description="账号通过推广落地页链接或账号 JSON 导入后，会进入这里统一管理。"
          />
        )}
      </ListTableCard>
      <Modal
        open={Boolean(testAccount)}
        onClose={() => !testPending && setTestAccount(null)}
        title="发送测试消息"
        description={`使用 ${testAccount?.phone || testAccount?.id || ""} 验证连接和送达状态。`}
        footer={
          <>
            <Button variant="outline" onClick={() => setTestAccount(null)}>
              关闭
            </Button>
            <Button
              disabled={testPending || !testTo.trim() || !testText.trim()}
              onClick={() => void sendTest()}
            >
              {testPending ? <Spinner /> : <MessageSquareTextIcon size={16} />}
              发送
            </Button>
          </>
        }
      >
        <label className="field">
          <span>接收号码（含国家码）</span>
          <Input
            value={testTo}
            onChange={(event) => setTestTo(event.target.value)}
            placeholder="例如：8613800000000"
          />
        </label>
        <label className="field">
          <span>测试内容</span>
          <Textarea
            rows={4}
            value={testText}
            onChange={(event) => setTestText(event.target.value)}
          />
        </label>
        {testResult ? (
          <div className="delivery-result">
            <CheckCheckIcon size={18} />
            <div>
              <strong>
                {testResult === "delivered"
                  ? "双勾 · 已送达"
                  : testResult === "server_accepted" || testResult === "sent"
                    ? "单勾 · 服务端已接收"
                    : testResult}
              </strong>
              <small>本系统不保存回复正文、已读状态或完整会话。</small>
            </div>
          </div>
        ) : null}
      </Modal>
    </StandardListPage>
  );
}
