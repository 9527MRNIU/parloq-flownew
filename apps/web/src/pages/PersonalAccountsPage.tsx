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
  UploadCloudIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  AccountStatusIndicator,
  accountUnifiedStatusKey,
} from "../components/account-status-indicator";
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
  Drawer,
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
import {
  accountRowKey,
  groupRowKey,
  snowflakeId,
} from "../lib/account-identifiers";
import { formatPhoneDisplay } from "../lib/utils";

type Account = {
  id: string;
  readKey: string;
  ownerId: string;
  phone: string;
  name: string;
  countryCode: string;
  status: string;
  connected: boolean;
  proxyId: string;
  proxyName: string;
  source: string;
  sourceRefType: string;
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
  id: string;
  name: string;
  countryCode: string;
  enabled: boolean;
};
type AccountGroup = { id: string; readKey: string; name: string; ownerId: string };
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
  const id = snowflakeId(
    row,
    "id",
    "accountId",
    "account_id",
    "snowflakeId",
    "snowflake_id",
  );
  const rawName = val(row, "displayName", "display_name", "name");
  return {
    id,
    readKey: accountRowKey(row, id),
    ownerId: val(row, "ownerId", "owner_id", "createdBy", "created_by"),
    phone: formatPhoneDisplay(
      val(row, "phoneNumber", "phone_number", "phone"),
    ),
    name: /^\+\d+$/.test(rawName)
      ? formatPhoneDisplay(rawName)
      : rawName,
    countryCode: val(row, "countryCode", "country_code"),
    status,
    connected: Boolean(
      row.connected ??
        ["connected", "online", "online_idle", "sending"].includes(status),
    ),
    proxyId:
      snowflakeId(row, "proxyId", "proxy_id") ||
      snowflakeId(proxy, "id", "proxyId", "proxy_id"),
    proxyName:
      val(row, "proxyName", "proxy_name") ||
      val(proxy, "proxyName", "proxy_name"),
    source: val(row, "source", "credentialSource", "credential_source"),
    sourceRefType: val(row, "sourceRefType", "source_ref_type"),
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
    groupId:
      snowflakeId(group, "id", "groupId", "group_id") ||
      snowflakeId(row, "groupId", "group_id"),
    groupName: val(group, "name") || val(row, "groupName", "group_name"),
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
    id: snowflakeId(row, "id", "proxyId", "proxy_id"),
    name: val(row, "name"),
    countryCode: val(row, "countryCode", "country_code"),
    enabled: Boolean(row.enabled ?? true),
  };
}
function sourceBadge(row: Account) {
  if (["landing_page", "landing", "pairing"].includes(row.source))
    return <Badge tone="info">落地页链接</Badge>;
  if (["json", "json_import", "import"].includes(row.source))
    return <Badge tone="neutral">JSON 导入</Badge>;
  return <Badge tone="neutral">待识别</Badge>;
}
const canSwitchProxy = (row: Account) =>
  ["linked_offline", "unpaired"].includes(row.status);

export function PersonalAccountsPage() {
  const { user, can } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const canImport = can("resources.accounts.import") || canManage;
  const [rows, setRows] = useState<Account[]>([]);
  const [proxies, setProxies] = useState<ProxyRow[]>([]);
  const [groups, setGroups] = useState<AccountGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
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
  const [importOpen, setImportOpen] = useState(
    searchParams.get("import") === "1",
  );
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importValidation, setImportValidation] = useState<{
    valid: boolean;
    message: string;
  } | null>(null);
  const [importValidating, setImportValidating] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [importProxyId, setImportProxyId] = useState("");
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
          .rows.map((row) => {
            const id = snowflakeId(row, "id", "groupId", "group_id");
            return {
              id,
              readKey: groupRowKey(row, id),
              name: val(row, "name"),
              ownerId: val(
                row,
                "ownerId",
                "owner_id",
                "createdBy",
                "created_by",
              ),
            };
          })
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
  useEffect(() => {
    if (searchParams.get("import") === "1") setImportOpen(true);
  }, [searchParams]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter(
      (row) =>
        (!search ||
          `${row.phone} ${row.name} ${row.id} ${row.countryCode} ${row.groupName} ${row.sourceRefType} ${row.importFormat} ${row.lastError}`
            .toLowerCase()
            .includes(search)) &&
        (statusFilter === "all" ||
          accountUnifiedStatusKey({
            status: row.status,
            connected: row.connected,
            validationStatus: row.validationStatus,
            metadataSyncStatus: row.metadataSyncStatus,
          }) === statusFilter) &&
        (sourceFilter === "all" || row.source === sourceFilter) &&
        (groupFilter === "all" ||
          (groupFilter === "__ungrouped__"
            ? !row.groupId
            : row.groupId === groupFilter)),
    );
  }, [
    groupFilter,
    keyword,
    rows,
    sourceFilter,
    statusFilter,
  ]);
  const visibleIds = visible.map((row) => row.id).filter(Boolean);
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
    name: "connect" | "disconnect" | "logout" | "sync",
  ) {
    if (!row.id) return;
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
      if (name === "sync") toast.success("资料同步任务已提交到后台");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setOperation("");
    }
  }
  async function bindProxy(row: Account, proxyId: string) {
    if (!row.id) return;
    try {
      await apiRequest(`/api/personal-accounts/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ proxyId: proxyId || null }),
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
    if (!row.id) return;
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
    if (!testAccount?.id || !testTo.trim() || !testText.trim()) return;
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
  function openImport() {
    setImportOpen(true);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("import", "1");
      return next;
    });
  }
  function closeImport() {
    if (importPending) return;
    setImportOpen(false);
    setImportFile(null);
    setImportValidation(null);
    setImportProxyId("");
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("import");
      return next;
    }, { replace: true });
  }
  async function chooseImport(next: File | null) {
    setImportFile(next);
    setImportValidation(null);
    if (!next) return;
    setImportValidating(true);
    try {
      if (!next.name.toLowerCase().endsWith(".json"))
        throw new Error("请选择 .json 文件");
      if (next.size > 10 * 1024 * 1024)
        throw new Error("JSON 文件不能超过 10 MB");
      const parsed = JSON.parse(await next.text()) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("JSON 顶层必须是对象");
      setImportValidation({
        valid: true,
        message: "文件已读取，导入时将继续检查账号信息。",
      });
    } catch (caught) {
      setImportValidation({
        valid: false,
        message: caught instanceof Error ? caught.message : "JSON 无法解析",
      });
    } finally {
      setImportValidating(false);
    }
  }
  async function submitImport() {
    if (!importFile || !importValidation?.valid || !canImport) return;
    setImportPending(true);
    try {
      const body = new FormData();
      body.set("file", importFile);
      if (importProxyId) body.set("proxyId", importProxyId);
      await apiRequest("/api/personal-accounts/import", {
        method: "POST",
        body,
      });
      await load();
      toast.success("账号 JSON 已导入统一账号池");
      setImportOpen(false);
      setImportFile(null);
      setImportValidation(null);
      setImportProxyId("");
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("import");
        return next;
      }, { replace: true });
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setImportPending(false);
    }
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索号码、名称或国家",
        }}
        filters={
          <>
            <SelectField
              ariaLabel="账号状态"
              className="w-[150px]"
              value={statusFilter}
              onValueChange={setStatusFilter}
              options={[
                { value: "all", label: "全部账号状态" },
                { value: "online", label: "在线" },
                { value: "offline", label: "离线" },
                { value: "processing", label: "处理中" },
                { value: "pending_validation", label: "待验证" },
                { value: "validating", label: "验证中" },
                { value: "validation_failed", label: "验证失败" },
                { value: "pending_sync", label: "待同步" },
                { value: "syncing", label: "同步中" },
                { value: "sync_failed", label: "同步失败" },
                { value: "error", label: "账号异常" },
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
            {canImport ? (
              <Button onClick={openImport}>
                <UploadCloudIcon size={16} />
                导入账号
              </Button>
            ) : null}
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
                    disabled={!canManage || !visibleIds.length}
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
                <TableHead>分组</TableHead>
                <TableHead>代理</TableHead>
                <TableHead>账号数据</TableHead>
                <TableHead className="sticky right-0 bg-background text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.readKey}>
                  <TableCell>
                    <Checkbox
                      aria-label={`选择账号 ${row.phone || row.name || "待迁移账号"}`}
                      checked={Boolean(row.id) && selectedIds.includes(row.id)}
                      disabled={!canManage || !row.id}
                      onCheckedChange={(checked) =>
                        row.id &&
                        setSelectedIds((current) =>
                          checked
                            ? [...new Set([...current, row.id])]
                            : current.filter((id) => id !== row.id),
                        )
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-[190px] items-start gap-3">
                      <AccountStatusIndicator
                        status={row.status}
                        connected={row.connected}
                        validationStatus={row.validationStatus}
                        metadataSyncStatus={row.metadataSyncStatus}
                        lastError={row.lastError}
                      />
                      <div className="cell-main min-w-0 max-w-[150px]">
                        <strong title={row.name || undefined}>
                          {row.phone || row.name || "账号待迁移"}
                        </strong>
                        {row.id ? (
                          <span title={row.id}>{row.id}</span>
                        ) : (
                          <span>等待 ID 迁移</span>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[120px] items-start">
                      {sourceBadge(row)}
                      {row.importFormat || row.sourceRefType ? (
                        <span
                          className="max-w-32 truncate"
                          title={[row.sourceRefType, row.importFormat]
                            .filter(Boolean)
                            .join(" · ")}
                        >
                          {row.importFormat || row.sourceRefType}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="cell-main min-w-[160px]">
                      <SelectField
                        ariaLabel={`账号 ${row.phone || "待迁移账号"} 的分组`}
                        className="w-[150px]"
                        value={row.groupId}
                        onValueChange={(groupId) =>
                          void changeGroup(row, groupId)
                        }
                        placeholder="未分组"
                        clearable
                        disabled={
                          !canManage || !row.id || groupingIds.includes(row.id)
                        }
                        options={groups
                          .filter((group) => group.ownerId === row.ownerId)
                          .map((group) => ({
                            value: group.id,
                            label: group.name,
                          }))}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    {user?.isAdmin ? (
                      <div className="cell-main">
                        <SelectField
                          ariaLabel="固定隔离代理"
                          className="w-[155px]"
                          value={row.proxyId}
                          onValueChange={(value) => void bindProxy(row, value)}
                          placeholder="系统自动分配"
                          clearable
                          disabled={
                            !canManage ||
                            !row.id ||
                            !canSwitchProxy(row) ||
                            Boolean(operation)
                          }
                          options={proxies
                            .filter((proxy) => proxy.enabled && proxy.id)
                            .map((proxy) => ({
                              value: proxy.id,
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
                    <div className="cell-main min-w-[160px] max-w-[180px]">
                      <div className="tick-stats">
                        <span><CheckCheckIcon size={14} />单勾 {row.accepted == null ? "-" : row.accepted}</span>
                        <span><CheckCheckIcon size={14} />双勾 {row.delivered == null ? "-" : row.delivered}</span>
                      </div>
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
                  <TableCell className="sticky right-0 bg-background">
                    {canManage ? <div className="flex items-center justify-end gap-1">
                      <IconButton
                        label="重新同步资料"
                        disabled={
                          !row.id ||
                          row.validationStatus !== "ready" ||
                          ["pairing", "reauth_required", "restricted"].includes(row.status) ||
                          Boolean(operation)
                        }
                        onClick={() => void action(row, "sync")}
                      >
                        <RefreshCwIcon
                          className={operation === `${row.id}:sync` ? "spin" : ""}
                          size={16}
                        />
                      </IconButton>
                      {row.connected ? (
                        <IconButton
                          label="断开"
                          disabled={!row.id || Boolean(operation)}
                          onClick={() => void action(row, "disconnect")}
                        >
                          <UnplugIcon size={16} />
                        </IconButton>
                      ) : (
                        <IconButton
                          label="连接"
                          disabled={!row.id || Boolean(operation)}
                          onClick={() => void action(row, "connect")}
                        >
                          <PowerIcon size={16} />
                        </IconButton>
                      )}
                      <IconButton
                        label="发测试消息"
                        disabled={!row.id || !row.connected}
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
                        disabled={!row.id || Boolean(operation)}
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
      <Drawer
        open={importOpen}
        onClose={closeImport}
        title="导入账号 JSON"
        description="导入完成后账号会直接进入当前统一账号池，无需离开账号管理。"
        footer={
          <>
            <Button variant="outline" disabled={importPending} onClick={closeImport}>
              取消
            </Button>
            <Button
              disabled={
                importPending ||
                importValidating ||
                !importFile ||
                !importValidation?.valid
              }
              onClick={() => void submitImport()}
            >
              {importPending ? <Spinner /> : <UploadCloudIcon size={16} />}
              校验并导入
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="upload-zone min-h-56">
            <Input
              type="file"
              accept=".json,application/json"
              disabled={importPending}
              onChange={(event) =>
                void chooseImport(event.target.files?.[0] || null)
              }
            />
            {importValidating ? <Spinner /> : <UploadCloudIcon size={30} />}
            <strong>{importFile?.name || "选择账号 JSON 文件"}</strong>
            <span>
              支持账号 JSON 与完整备份，最大 10 MB
            </span>
          </label>
          {importValidation ? (
            <div
              className={`rounded-lg border p-3 text-sm ${
                importValidation.valid
                  ? "border-emerald-600/20 bg-emerald-600/5 text-emerald-700 dark:text-emerald-400"
                  : "border-destructive/20 bg-destructive/5 text-destructive"
              }`}
            >
              {importValidation.message}
            </div>
          ) : null}
          {user?.isAdmin ? (
            <label className="field">
              <span>固定 IP（可选）</span>
              <SelectField
                value={importProxyId}
                onValueChange={setImportProxyId}
                options={proxies
                  .filter((proxy) => proxy.enabled && proxy.id)
                  .map((proxy) => ({
                    value: proxy.id,
                    label: `${proxy.name}${proxy.countryCode ? ` · ${proxy.countryCode}` : ""}`,
                  }))}
                placeholder="按当前 IP 分配策略自动选择"
                clearable
                disabled={importPending}
              />
              <small className="field-help">
                只有“仅手动分配”模式必须选择，其他模式可留空。
              </small>
            </label>
          ) : null}
          <div className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">
            <strong className="text-foreground">入池规则</strong>
            <p className="mt-2 leading-6">
              导入后会检查账号状态，验证成功后即可使用；资料尚未完成同步时显示“待同步”。
            </p>
          </div>
        </div>
      </Drawer>
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
            onChange={(event) =>
              setTestTo(event.target.value.replace(/\D/g, ""))
            }
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
