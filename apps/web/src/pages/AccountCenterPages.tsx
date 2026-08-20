import {
  DownloadIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  apiDownload,
  apiRequest,
  formatDateTime,
  unwrapList,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AccountStatusIndicator } from "../components/account-status-indicator";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import {
  ListPagination,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
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
import { DrawerFieldLabel } from "../components/drawer-form";

const field = (row: Record<string, unknown>, ...keys: string[]) => {
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

type ExportAccount = {
  id: string;
  readKey: string;
  phone: string;
  name: string;
  countryCode: string;
  status: string;
  source: string;
  connected: boolean;
  validationStatus: string;
  metadataSyncStatus: string;
  lastError: string;
  groupId: string;
  groupName: string;
  createdAt: string;
};

function exportAccount(input: unknown): ExportAccount {
  const row = input as Record<string, unknown>;
  const status = field(row, "connectionStatus", "connection_status", "status");
  const group = (row.group || {}) as Record<string, unknown>;
  const id = snowflakeId(
    row,
    "id",
    "accountId",
    "account_id",
    "snowflakeId",
    "snowflake_id",
  );
  const rawName = field(row, "displayName", "display_name", "name");
  return {
    id,
    readKey: accountRowKey(row, id),
    phone: formatPhoneDisplay(
      field(row, "phoneNumber", "phone_number", "phone"),
    ),
    name: /^\+\d+$/.test(rawName)
      ? formatPhoneDisplay(rawName)
      : rawName,
    countryCode: field(row, "countryCode", "country_code"),
    status: status || "offline",
    source: field(row, "source", "credentialSource", "credential_source"),
    connected: Boolean(
      row.connected ?? ["connected", "online", "online_idle", "sending"].includes(status),
    ),
    validationStatus: field(row, "validationStatus", "validation_status"),
    metadataSyncStatus: field(row, "metadataSyncStatus", "metadata_sync_status"),
    lastError: field(row, "lastError", "last_error"),
    groupId:
      snowflakeId(group, "id", "groupId", "group_id") ||
      snowflakeId(row, "groupId", "group_id"),
    groupName:
      field(group, "name") || field(row, "groupName", "group_name"),
    createdAt: field(row, "createdAt", "created_at"),
  };
}

const exportable = (row: ExportAccount) =>
  Boolean(row.id) &&
  row.validationStatus === "ready" &&
  !["pairing", "warming", "online_idle", "sending", "draining"].includes(
    row.status,
  );

function sourceBadge(source: string) {
  if (["landing_page", "landing", "pairing"].includes(source))
    return <Badge tone="info">落地页链接</Badge>;
  if (["json", "json_import", "import"].includes(source))
    return <Badge tone="neutral">JSON 导入</Badge>;
  return <Badge tone="neutral">待识别</Badge>;
}

export function AccountExportPage() {
  const { can } = useAuth();
  const canManage =
    can("resources.accounts.export") ||
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [rows, setRows] = useState<ExportAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [connectionFilter, setConnectionFilter] = useState("all");
  const [validationFilter, setValidationFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [groupFilter, setGroupFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [exporting, setExporting] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest("/api/personal-accounts?pageSize=100");
      const nextRows = unwrapList<unknown>(payload).rows.map(exportAccount);
      setRows(nextRows);
      setSelectedIds((current) =>
        current.filter((id) =>
          nextRows.some((row) => row.id === id && exportable(row)),
        ),
      );
    } catch (caught) {
      setRows([]);
      toast.error(caught instanceof Error ? caught.message : "账号加载失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => void load(), [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter(
      (row) =>
        (!search ||
          `${row.phone} ${row.name} ${row.id} ${row.countryCode} ${row.groupName}`
            .toLowerCase()
            .includes(search)) &&
        (connectionFilter === "all" ||
          (connectionFilter === "online" ? row.connected : !row.connected)) &&
        (validationFilter === "all" ||
          (validationFilter === "exportable"
            ? exportable(row)
            : row.validationStatus === validationFilter)) &&
        (sourceFilter === "all" || row.source === sourceFilter) &&
        (groupFilter === "all" ||
          (groupFilter === "__ungrouped__"
            ? !row.groupId
            : row.groupId === groupFilter)),
    );
  }, [
    connectionFilter,
    groupFilter,
    keyword,
    rows,
    sourceFilter,
    validationFilter,
  ]);
  const groupOptions = useMemo(
    () =>
      Array.from(
        new Map(
          rows
            .filter((row) => row.groupId)
            .map((row) => [row.groupId, row.groupName || row.groupId]),
        ),
      ).map(([value, label]) => ({ value, label })),
    [rows],
  );
  const exportPagination = useClientPagination(visible, {
    resetKey: `${keyword}|${connectionFilter}|${validationFilter}|${sourceFilter}|${groupFilter}`,
  });
  const selectableIds = visible.filter(exportable).map((row) => row.id);
  const allVisibleSelected =
    Boolean(selectableIds.length) &&
    selectableIds.every((id) => selectedIds.includes(id));

  function saveDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function download(row: ExportAccount, format: "baileys_creds" | "native") {
    if (!row.id) return;
    const operation = `${row.id}:${format}`;
    setExporting(operation);
    try {
      const response = await apiDownload(`/api/personal-accounts/${row.id}/export?format=${format}`);
      saveDownload(
        response.blob,
        response.filename
          ? decodeURIComponent(response.filename)
          : `${row.phone || row.id}${format === "native" ? "-parloq-full" : ""}.json`,
      );
      toast.success("账号 JSON 已生成，请妥善保管凭据文件");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导出失败");
    } finally {
      setExporting("");
    }
  }

  async function downloadBatch(format: "baileys_creds" | "native") {
    if (!selectedIds.length) return;
    if (
      !(await confirmAction({
        title: `导出所选 ${selectedIds.length} 个账号？`,
        description:
          "系统会生成一个 ZIP，包内每个 JSON 都包含敏感登录凭据，请仅保存到受控设备。",
        confirmText: "确认导出",
      }))
    )
      return;
    const operation = `batch:${format}`;
    setExporting(operation);
    try {
      const response = await apiDownload("/api/personal-accounts/export/batch", {
        method: "POST",
        body: JSON.stringify({ accountIds: selectedIds, format }),
      });
      saveDownload(
        response.blob,
        response.filename
          ? decodeURIComponent(response.filename)
          : `parloq-accounts-${format}.zip`,
      );
      toast.success(`已生成 ${selectedIds.length} 个账号的导出包`);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "批量导出失败");
    } finally {
      setExporting("");
    }
  }

  return (
    <StandardListPage viewport>
      <div className="notice-warning rounded-lg border px-4 py-3 text-sm">
        “兼容 JSON”可用于其他支持相同账号格式的环境；“完整备份”适合本系统间迁移。导出文件可用于登录账号，请妥善保管。
      </div>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索号码、名称或账号 ID" }}
        filters={
          <>
            <SelectField
              ariaLabel="连接状态"
              className="w-[140px]"
              value={connectionFilter}
              onValueChange={setConnectionFilter}
              options={[
                { value: "all", label: "全部连接状态" },
                { value: "online", label: "在线" },
                { value: "offline", label: "离线" },
              ]}
            />
            <SelectField
              ariaLabel="导出条件"
              className="w-[140px]"
              value={validationFilter}
              onValueChange={setValidationFilter}
              options={[
                { value: "all", label: "全部导出条件" },
                { value: "exportable", label: "当前可导出" },
                { value: "ready", label: "验证通过" },
                { value: "validating", label: "验证中" },
                { value: "failed", label: "验证失败" },
              ]}
            />
            <SelectField
              ariaLabel="账号来源"
              className="w-[135px]"
              value={sourceFilter}
              onValueChange={setSourceFilter}
              options={[
                { value: "all", label: "全部来源" },
                { value: "landing_page", label: "落地页链接" },
                { value: "json_import", label: "JSON 导入" },
              ]}
            />
            <SelectField
              ariaLabel="账号分组"
              className="w-[145px]"
              value={groupFilter}
              onValueChange={setGroupFilter}
              options={[
                { value: "all", label: "全部分组" },
                { value: "__ungrouped__", label: "未分组" },
                ...groupOptions,
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
            {selectedIds.length ? (
              <>
                <Button
                  variant="outline"
                  disabled={Boolean(exporting)}
                  onClick={() => void downloadBatch("baileys_creds")}
                >
                  {exporting === "batch:baileys_creds" ? <Spinner /> : <DownloadIcon size={15} />}
                  导出兼容包
                </Button>
                <Button
                  disabled={Boolean(exporting)}
                  onClick={() => void downloadBatch("native")}
                >
                  {exporting === "batch:native" ? <Spinner /> : <DownloadIcon size={15} />}
                  导出完整包
                </Button>
              </>
            ) : null}
            <Button variant="outline" onClick={() => void load()} disabled={loading}>
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新
            </Button>
          </>
        }
      />
      <ListPagination
        page={exportPagination.page}
        pageSize={exportPagination.pageSize}
        total={exportPagination.total}
        disabled={loading}
        onPageChange={exportPagination.setPage}
        onPageSizeChange={exportPagination.setPageSize}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载账号…</div> : visible.length ? (
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-10">
                <Checkbox
                  aria-label="选择全部可导出账号"
                  checked={allVisibleSelected}
                  disabled={!canManage || !selectableIds.length}
                  onCheckedChange={(checked) =>
                    setSelectedIds((current) =>
                      checked
                        ? Array.from(new Set([...current, ...selectableIds]))
                        : current.filter((id) => !selectableIds.includes(id)),
                    )
                  }
                />
              </TableHead>
              <TableHead>账号</TableHead><TableHead>来源</TableHead><TableHead>分组</TableHead><TableHead>导出条件</TableHead><TableHead>入库时间</TableHead><TableHead className="text-right">操作</TableHead>
            </TableRow></TableHeader>
            <TableBody>{exportPagination.rows.map((row) => (
              <TableRow key={row.readKey}>
                <TableCell>
                  <Checkbox
                    aria-label={`选择账号 ${row.phone || row.name || "待迁移账号"}`}
                    checked={Boolean(row.id) && selectedIds.includes(row.id)}
                    disabled={!canManage || !exportable(row)}
                    onCheckedChange={(checked) =>
                      setSelectedIds((current) =>
                        checked
                          ? Array.from(new Set([...current, row.id]))
                          : current.filter((id) => id !== row.id),
                      )
                    }
                  />
                </TableCell>
                <TableCell>
                  <div className="flex min-w-[220px] items-start gap-3">
                    <AccountStatusIndicator
                      status={row.status}
                      connected={row.connected}
                      validationStatus={row.validationStatus}
                      metadataSyncStatus={row.metadataSyncStatus}
                      lastError={row.lastError}
                    />
                    <div className="cell-main min-w-0">
                      <strong title={row.name || undefined}>{row.phone || row.name || "账号待迁移"}</strong>
                      {row.id ? (
                        <span title={row.id}>{row.id}</span>
                      ) : (
                        <span>等待 ID 迁移</span>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell>{sourceBadge(row.source)}</TableCell>
                <TableCell>
                  {row.groupId || row.groupName ? (
                    <div className="cell-main min-w-[140px]">
                      <strong>{row.groupName || "未命名分组"}</strong>
                      {row.groupId ? (
                        <span title={row.groupId}>
                          {row.groupId}
                        </span>
                      ) : (
                        <span>等待 ID 迁移</span>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted-foreground">未分组</span>
                  )}
                </TableCell>
                <TableCell>
                  {exportable(row) ? (
                    <Badge tone="success">可导出</Badge>
                  ) : row.connected ? (
                    <Badge tone="warning">请先断开</Badge>
                  ) : row.validationStatus === "failed" ? (
                    <Badge tone="danger">验证失败</Badge>
                  ) : (
                    <Badge tone="neutral">等待验证</Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                <TableCell><div className="flex justify-end gap-2"><Button variant="outline" size="sm" disabled={!canManage || !exportable(row) || Boolean(exporting)} onClick={() => void download(row, "baileys_creds")}>{exporting === `${row.id}:baileys_creds` ? <Spinner /> : <DownloadIcon size={15} />}兼容 JSON</Button><Button variant="outline" size="sm" disabled={!canManage || !exportable(row) || Boolean(exporting)} onClick={() => void download(row, "native")}>{exporting === `${row.id}:native` ? <Spinner /> : <DownloadIcon size={15} />}完整备份</Button></div></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        ) : <EmptyState title="暂无可导出的账号" description="账号通过落地页链接或 JSON 导入后，会出现在这里。" />}
      </ListTableCard>
    </StandardListPage>
  );
}

type AccountGroup = {
  id: string;
  readKey: string;
  name: string;
  description: string;
  accountCount: number | null;
  createdAt: string;
};
function accountGroup(input: unknown): AccountGroup {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id", "groupId", "group_id");
  return {
    id,
    readKey: groupRowKey(row, id),
    name: field(row, "name"),
    description: field(row, "description"),
    accountCount: optionalNumber(row, "accountCount", "account_count"),
    createdAt: field(row, "createdAt", "created_at"),
  };
}

export function AccountGroupsPage() {
  const { can } = useAuth();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [rows, setRows] = useState<AccountGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AccountGroup | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest("/api/account-groups?pageSize=100");
      setRows(unwrapList<unknown>(payload).rows.map(accountGroup));
    } catch (caught) {
      setRows([]);
      toast.error(caught instanceof Error ? caught.message : "分组加载失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => void load(), [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search ? rows.filter((row) => `${row.name} ${row.description}`.toLowerCase().includes(search)) : rows;
  }, [keyword, rows]);
  const groupPagination = useClientPagination(visible, { resetKey: keyword });
  function edit(row?: AccountGroup) {
    setEditing(row || null);
    setName(row?.name || "");
    setDescription(row?.description || "");
    setOpen(true);
  }
  async function save() {
    if (!name.trim()) return;
    if (editing && !editing.id) return;
    setPending(true);
    try {
      await apiRequest(editing ? `/api/account-groups/${editing.id}` : "/api/account-groups", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
      });
      setOpen(false);
      await load();
      toast.success(editing ? "账号分组已更新" : "账号分组已创建");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }
  async function remove(row: AccountGroup) {
    if (!row.id) return;
    if (!(await confirmAction({ title: `删除分组“${row.name}”？`, description: "分组内账号不会被删除，将回到未分组状态。", confirmText: "删除分组" }))) return;
    try {
      await apiRequest(`/api/account-groups/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("账号分组已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索分组名称或说明" }}
        meta={`${visible.length} 个分组`}
        actions={<><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新</Button>{canManage ? <Button onClick={() => edit()}><PlusIcon size={16} />新建分组</Button> : null}</>}
      />
      <ListPagination
        page={groupPagination.page}
        pageSize={groupPagination.pageSize}
        total={groupPagination.total}
        disabled={loading}
        onPageChange={groupPagination.setPage}
        onPageSizeChange={groupPagination.setPageSize}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载账号分组…</div> : visible.length ? (
          <Table><TableHeader><TableRow><TableHead>分组</TableHead><TableHead>说明</TableHead><TableHead>账号数</TableHead><TableHead>创建时间</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader>
            <TableBody>{groupPagination.rows.map((row) => <TableRow key={row.readKey}>
              <TableCell>
                <EntityPrimaryCell
                  title={row.name}
                  id={row.id}
                  status={{
                    label: "可用",
                    description: "分组可以正常用于组织、筛选和批量管理账号。",
                    tone: "success",
                    details: [
                      { label: "账号数", value: row.accountCount == null ? "待同步" : row.accountCount },
                      { label: "说明", value: row.description || "暂无说明" },
                    ],
                  }}
                />
              </TableCell>
              <TableCell className="max-w-[360px] text-muted-foreground">{row.description || "暂无说明"}</TableCell>
              <TableCell>{row.accountCount == null ? <span className="text-muted-foreground">待同步</span> : row.accountCount}</TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              <TableCell><div className="flex justify-end gap-1">{canManage ? <><IconButton label="编辑分组" disabled={!row.id} onClick={() => edit(row)}><PencilIcon size={15} /></IconButton><IconButton label="删除分组" className="text-destructive" disabled={!row.id} onClick={() => void remove(row)}><Trash2Icon size={15} /></IconButton></> : null}</div></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        ) : <EmptyState title="还没有账号分组" description="创建分组后可按用途、国家或客户业务组织统一账号池。" />}
      </ListTableCard>
      <Drawer open={open} onClose={() => !pending && setOpen(false)} title={editing ? "编辑账号分组" : "新建账号分组"} description="分组仅用于组织和筛选，不改变账号凭据或连接状态。" footer={<><Button variant="outline" onClick={() => setOpen(false)}>取消</Button><Button disabled={pending || !name.trim()} onClick={() => void save()}>{pending ? <Spinner /> : null}保存</Button></>}>
        <div className="drawer-form"><label className="field"><DrawerFieldLabel required>分组名称</DrawerFieldLabel><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：美国推广账号" /></label><label className="field"><DrawerFieldLabel>分组说明</DrawerFieldLabel><Textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="说明用途、地区或运营规则" /></label></div>
      </Drawer>
    </StandardListPage>
  );
}

type IntakeAttempt = {
  id: string;
  attemptType: string;
  status: string;
  terminalReason: string;
  providerCode: string;
  failureReason?: {
    code: string;
    label: string;
    detailCode: string;
    providerCode: string;
  } | null;
  account: {
    id: string;
    name: string;
    phone: string;
    admissionStatus: string;
    status: string;
    validationStatus: string;
    metadataSyncStatus: string;
  };
  channel: { id: string; name: string } | null;
  protocol: { id: string; name: string } | null;
  group: { id: string; name: string } | null;
  syncJob: { id: string; status: string; lastError: string } | null;
  expiresAt: string;
  verifiedAt: string;
  createdAt: string;
};

const attemptLabel: Record<string, string> = {
  code_issued: "配对码已生成",
  waiting_phone: "等待手机确认",
  reconnecting: "配对连接恢复中",
  verified: "验证成功",
  expired: "配对码已过期",
  cancelled: "用户已取消",
  failed: "绑定失败",
};

const failureReasonLabel: Record<string, string> = {
  invalid_phone: "号码无效",
  invalid_request: "请求信息无效",
  number_unavailable: "号码不可用",
  pairing_in_progress: "号码正在配对",
  rate_limited: "请求限速",
  protocol_unavailable: "协议节点不可用",
  configuration_unavailable: "渠道配置不可用",
  connection_route_unavailable: "连接线路不可用",
  gateway_failed: "网关失败",
  pairing_start_failed: "网关启动失败",
  pairing_failed: "网关配对失败",
  pairing_connection_lost: "配对连接中断",
  pairing_expired: "配对码过期",
  pairing_cancelled: "用户取消",
  service_unavailable: "服务暂时不可用",
  failed: "其他配对失败",
  expired: "配对码过期",
  cancelled: "用户取消",
  unknown: "其他失败",
};

function attemptFailureReason(attempt: IntakeAttempt) {
  const detailCode =
    attempt.failureReason?.detailCode || attempt.terminalReason || attempt.status;
  const label =
    attempt.failureReason?.label ||
    failureReasonLabel[detailCode] ||
    failureReasonLabel[attempt.failureReason?.code || ""] ||
    "其他失败";
  return {
    label,
    detailCode,
    providerCode:
      attempt.failureReason?.providerCode || attempt.providerCode || "",
  };
}

function attemptBadge(status: string) {
  if (status === "verified") return <Badge tone="success">验证成功</Badge>;
  if (["failed", "expired", "cancelled"].includes(status))
    return <Badge tone={status === "failed" ? "danger" : "neutral"}>{attemptLabel[status] || status}</Badge>;
  return <Badge tone="warning">{attemptLabel[status] || status}</Badge>;
}

function admissionBadge(status: string) {
  if (status === "active") return <Badge tone="success">已正式入池</Badge>;
  if (status === "reserved") return <Badge tone="warning">接入预留</Badge>;
  return <Badge tone="neutral">未进入账号池</Badge>;
}

export function AccountIntakePage() {
  const [rows, setRows] = useState<IntakeAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
      });
      if (query) params.set("keyword", query);
      if (statusFilter !== "all") params.set("status", statusFilter);
      const payload = await apiRequest(`/api/personal-accounts/intake/attempts?${params}`);
      const list = unwrapList<IntakeAttempt>(payload);
      setRows(list.rows);
      setTotal(list.total);
    } catch (caught) {
      setRows([]);
      setTotal(0);
      toast.error(caught instanceof Error ? caught.message : "接入记录加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query, statusFilter]);

  useEffect(() => void load(), [load]);

  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          onSubmit: () => {
            setPage(1);
            setQuery(keyword.trim());
          },
          placeholder: "搜索号码、账号名称或接入 ID",
        }}
        filters={
          <SelectField
            ariaLabel="接入状态"
            className="w-[165px]"
            value={statusFilter}
            onValueChange={(value) => {
              setPage(1);
              setStatusFilter(value);
            }}
            options={[
              { value: "all", label: "全部接入状态" },
              { value: "waiting_phone", label: "等待手机确认" },
              { value: "reconnecting", label: "连接恢复中" },
              { value: "verified", label: "验证成功" },
              { value: "failed", label: "绑定失败" },
              { value: "expired", label: "配对码过期" },
              { value: "cancelled", label: "用户取消" },
            ]}
          />
        }
        meta={`${total} 条接入记录`}
        actions={
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新
          </Button>
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
          <div className="loading-state"><Spinner />正在加载接入记录…</div>
        ) : rows.length ? (
          <Table>
            <TableHeader><TableRow>
              <TableHead>号码 / 账号</TableHead>
              <TableHead>接入类型</TableHead>
              <TableHead>接入状态</TableHead>
              <TableHead>入池结果</TableHead>
              <TableHead>渠道</TableHead>
              <TableHead>协议 / 分组</TableHead>
              <TableHead>资料同步</TableHead>
              <TableHead>发起时间</TableHead>
            </TableRow></TableHeader>
            <TableBody>{rows.map((row) => {
              const failure = attemptFailureReason(row);
              return (
              <TableRow key={row.id}>
                <TableCell>
                  <div className="cell-main min-w-[210px]">
                    <strong>{formatPhoneDisplay(row.account.phone) || row.account.name}</strong>
                    <span title={row.account.id}>{row.account.id}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge tone={row.attemptType === "reauthentication" ? "info" : "neutral"}>
                    {row.attemptType === "reauthentication" ? "重新认证" : "首次绑定"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex min-w-[150px] flex-col items-start gap-1">
                    {attemptBadge(row.status)}
                          {row.failureReason || row.terminalReason ? (
                      <span
                        className="text-xs text-muted-foreground"
                        title={[
                          `内部原因：${failure.detailCode}`,
                          failure.providerCode
                            ? `提供方代码：${failure.providerCode}`
                            : "",
                        ]
                          .filter(Boolean)
                          .join("；")}
                      >
                        {failure.label}
                        {failure.providerCode
                          ? ` · 提供方 ${failure.providerCode}`
                          : ""}
                      </span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>{admissionBadge(row.account.admissionStatus)}</TableCell>
                <TableCell>
                  <div className="cell-main min-w-[140px]">
                    <strong>{row.channel?.name || "渠道已删除"}</strong>
                    <span>{row.channel?.id || "-"}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="cell-main min-w-[170px]">
                    <strong>{row.protocol?.name || "协议不可用"}</strong>
                    <span>{row.group?.name || "未分组"}</span>
                  </div>
                </TableCell>
                <TableCell>
                  {row.syncJob ? (
                    <Badge tone={row.syncJob.status === "succeeded" ? "success" : row.syncJob.status === "failed" ? "danger" : "warning"}>
                      {row.syncJob.status === "succeeded" ? "同步完成" : row.syncJob.status === "failed" ? "同步失败" : "后台同步中"}
                    </Badge>
                  ) : <span className="text-muted-foreground">尚未触发</span>}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              </TableRow>
              );
            })}</TableBody>
          </Table>
        ) : (
          <EmptyState title="暂无接入记录" description="访客从渠道落地页发起首次绑定或重新认证后，会显示在这里。" />
        )}
      </ListTableCard>
    </StandardListPage>
  );
}
