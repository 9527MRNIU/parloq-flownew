import {
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  ExternalLinkIcon,
  Globe2Icon,
  PlusIcon,
  RefreshCwIcon,
  RouteIcon,
  SlidersHorizontalIcon,
  UserRoundIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  apiDownload,
  apiRequest,
  formatDateTime,
  unwrapList,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AccountStatusIndicator } from "../components/account-status-indicator";
import { CountryDisplay } from "../components/country-display";
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import { MonitoringLandingCell } from "../components/monitoring-landing-cell";
import {
  ListPagination,
  ListSortableHead,
  type ListSortOrder,
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
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  SearchableSelect,
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
import {
  RecordDataSection,
  RecordDetailField,
  RecordDetailSection,
  RecordDetailSummaryCard,
  RecordDetailSummaryGrid,
} from "../components/record-detail";

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

type AccountGroup = {
  id: string;
  readKey: string;
  name: string;
  description: string;
  accountCount: number | null;
  validAccountCount: number | null;
  validRate: number | null;
  averageScore: number | null;
  onlineAccountCount: number | null;
  abnormalAccountCount: number | null;
  pendingValidationCount: number | null;
  profileKnownCount: number | null;
  profileCompleteCount: number | null;
  profileCompleteRate: number | null;
  profileUnknownCount: number | null;
  noAvatarCount: number | null;
  noGroupCount: number | null;
  zeroFriendCount: number | null;
  createdAt: string;
  updatedAt: string;
};
type AccountGroupSortBy =
  | "id"
  | "accountCount"
  | "validAccountCount"
  | "abnormalAccountCount"
  | "validRate"
  | "averageScore"
  | "createdAt"
  | "updatedAt";
function accountGroup(input: unknown): AccountGroup {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id", "groupId", "group_id");
  return {
    id,
    readKey: groupRowKey(row, id),
    name: field(row, "name"),
    description: field(row, "description"),
    accountCount: optionalNumber(row, "accountCount", "account_count"),
    validAccountCount: optionalNumber(
      row,
      "validAccountCount",
      "valid_account_count",
    ),
    validRate: optionalNumber(row, "validRate", "valid_rate"),
    averageScore: optionalNumber(row, "averageScore", "average_score"),
    onlineAccountCount: optionalNumber(
      row,
      "onlineAccountCount",
      "online_account_count",
    ),
    abnormalAccountCount: optionalNumber(
      row,
      "abnormalAccountCount",
      "abnormal_account_count",
    ),
    pendingValidationCount: optionalNumber(
      row,
      "pendingValidationCount",
      "pending_validation_count",
    ),
    profileKnownCount: optionalNumber(
      row,
      "profileKnownCount",
      "profile_known_count",
    ),
    profileCompleteCount: optionalNumber(
      row,
      "profileCompleteCount",
      "profile_complete_count",
    ),
    profileCompleteRate: optionalNumber(
      row,
      "profileCompleteRate",
      "profile_complete_rate",
    ),
    profileUnknownCount: optionalNumber(
      row,
      "profileUnknownCount",
      "profile_unknown_count",
    ),
    noAvatarCount: optionalNumber(row, "noAvatarCount", "no_avatar_count"),
    noGroupCount: optionalNumber(row, "noGroupCount", "no_group_count"),
    zeroFriendCount: optionalNumber(
      row,
      "zeroFriendCount",
      "zero_friend_count",
    ),
    createdAt: field(row, "createdAt", "created_at"),
    updatedAt: field(row, "updatedAt", "updated_at"),
  };
}

export function AccountGroupsPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const canManage =
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [rows, setRows] = useState<AccountGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [sortBy, setSortBy] = useState<AccountGroupSortBy>("id");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AccountGroup | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      query.set("sortBy", sortBy);
      query.set("sortOrder", sortOrder);
      const payload = await apiRequest(`/api/account-groups?${query}`);
      const list = unwrapList<unknown>(payload);
      setRows(list.rows.map(accountGroup));
      setTotal(list.total);
    } catch (caught) {
      setRows([]);
      setTotal(0);
      toast.error(caught instanceof Error ? caught.message : "分组加载失败");
    } finally {
      setLoading(false);
    }
  }, [debouncedKeyword, page, pageSize, sortBy, sortOrder]);
  useEffect(() => void load(), [load]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);
  function changeSort(nextSortBy: AccountGroupSortBy, nextSortOrder: ListSortOrder) {
    setSortBy(nextSortBy);
    setSortOrder(nextSortOrder);
    setPage(1);
  }
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
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索分组名称或备注" }}
        meta={`${total} 个分组`}
        actions={<><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新</Button>{canManage ? <Button onClick={() => edit()}><PlusIcon size={16} />新建分组</Button> : null}</>}
      />
      <ListPagination
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载账号分组…</div> : rows.length ? (
          <Table layout="list"><TableHeader><TableRow>
            <ListSortableHead sortKey="id" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>分组</ListSortableHead>
            <TableHead adaptive>备注</TableHead>
            <ListSortableHead sortKey="accountCount" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>账号总数</ListSortableHead>
            <ListSortableHead sortKey="validAccountCount" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>有效账号</ListSortableHead>
            <ListSortableHead sortKey="abnormalAccountCount" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>异常账号</ListSortableHead>
            <ListSortableHead sortKey="validRate" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>有效率</ListSortableHead>
            <ListSortableHead sortKey="averageScore" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>评分</ListSortableHead>
            <ListSortableHead sortKey="createdAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>创建时间</ListSortableHead>
            <ListSortableHead sortKey="updatedAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>更新时间</ListSortableHead>
            <TableHead>操作</TableHead>
          </TableRow></TableHeader>
            <TableBody>{rows.map((row) => <TableRow key={row.readKey}>
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
                      { label: "备注", value: row.description || "暂无备注" },
                    ],
                  }}
                />
              </TableCell>
              <TableCell className="max-w-[360px] text-muted-foreground">{row.description || "暂无备注"}</TableCell>
              <TableCell className="text-center tabular-nums">{row.accountCount ?? "-"}</TableCell>
              <TableCell className="text-center tabular-nums">{row.validAccountCount ?? "-"}</TableCell>
              <TableCell className="text-center tabular-nums">{row.abnormalAccountCount ?? "-"}</TableCell>
              <TableCell className="text-center tabular-nums">{row.validRate == null ? "-" : `${(row.validRate <= 1 ? row.validRate * 100 : row.validRate).toFixed(1)}%`}</TableCell>
              <TableCell className="text-center tabular-nums">{row.averageScore == null ? "待同步" : `${row.averageScore} 分`}</TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.updatedAt)}</TableCell>
              <TableCell><div className="flex min-w-max justify-end gap-2"><Button variant="outline" size="sm" disabled={!row.id} onClick={() => navigate(`/resources/accounts/manage?groupId=${encodeURIComponent(row.id)}`)}><EyeIcon size={16} />查看账号</Button>{canManage ? <><Button variant="outline" size="sm" disabled={!row.id} onClick={() => edit(row)}>编辑</Button><Button variant="destructive" size="sm" disabled={!row.id} onClick={() => void remove(row)}>删除</Button></> : null}</div></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        ) : <EmptyState title="还没有账号分组" description="创建分组后可按用途、国家或客户业务组织统一账号池。" />}
      </ListTableCard>
      <Drawer open={open} onClose={() => !pending && setOpen(false)} title={editing ? "编辑账号分组" : "新建账号分组"} description="分组仅用于组织和筛选，不改变账号凭据或连接状态。" footer={<><Button variant="outline" onClick={() => setOpen(false)}>取消</Button><Button disabled={pending || !name.trim()} onClick={() => void save()}>{pending ? <Spinner /> : null}保存</Button></>}>
        <div className="drawer-form"><label className="field"><DrawerFieldLabel required>分组名称</DrawerFieldLabel><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：美国推广账号" /></label><label className="field"><DrawerFieldLabel>备注</DrawerFieldLabel><Textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="备注用途、地区或运营规则" /></label></div>
      </Drawer>
    </StandardListPage>
  );
}

type IntakeAttempt = {
  id: string;
  publicId?: string | null;
  visitorId?: string | null;
  attemptType: string;
  status: string;
  terminalReason: string;
  providerCode: string;
  failureDetail?: {
    code: string;
    title: string;
    message: string;
    suggestion: string;
    stage: string;
    retryable: boolean;
    protocolCode?: string;
    technicalMessage?: string;
  } | null;
  sourceIp?: string | null;
  visitorCountryCode?: string | null;
  networkSource?: string | null;
  requestContext?: Record<string, unknown>;
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
    countryCode?: string | null;
    admissionStatus: string;
    status: string;
    validationStatus: string;
    metadataSyncStatus: string;
  };
  channel: { id: string; name: string; slug: string } | null;
  landing: { hostname?: string | null; url: string } | null;
  template: { id: string; name: string; version: string } | null;
  protocol: { id: string; name: string } | null;
  group: { id: string; name: string } | null;
  routeVersion?: number | null;
  syncPolicyVersion?: number | null;
  syncJob: { id: string; status: string; lastError: string } | null;
  expiresAt: string;
  verifiedAt: string;
  createdAt: string;
  updatedAt?: string;
};
type IntakeSortBy =
  | "accountId"
  | "status"
  | "pairingType"
  | "countryCode"
  | "visitorCountryCode"
  | "channelId"
  | "admissionStatus"
  | "metadataStatus"
  | "createdAt";
type IntakeFilterOption = { id: string; name: string };

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
    attempt.failureDetail?.title ||
    attempt.failureReason?.label ||
    failureReasonLabel[detailCode] ||
    failureReasonLabel[attempt.failureReason?.code || ""] ||
    "其他失败";
  return {
    label,
    detailCode,
    providerCode:
      attempt.failureDetail?.protocolCode ||
      attempt.failureReason?.providerCode || attempt.providerCode || "",
  };
}

const failureStageLabel: Record<string, string> = {
  connection_route: "账号连接线路",
  prepare_pairing: "准备配对通道",
  resolve_wa_version: "获取 WhatsApp 版本",
  wait_pair_success: "等待手机确认",
  pairing_start: "启动配对",
  connection: "协议连接",
};

function FailureDiagnosisCard({ attempt }: { attempt: IntakeAttempt }) {
  const failure = attempt.failureDetail;
  const reason = attemptFailureReason(attempt);
  if (!failure && !attempt.terminalReason) return null;
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-3 flex items-center gap-2">
        <Badge tone={attempt.status === "failed" ? "danger" : "neutral"}>
          {attemptLabel[attempt.status] || "接入异常"}
        </Badge>
        <strong>{failure?.title || reason.label}</strong>
      </div>
      {failure?.message ? (
        <p className="mb-2 text-sm text-muted-foreground">{failure.message}</p>
      ) : null}
      {failure?.suggestion ? (
        <p className="mb-3 text-sm">
          <span className="font-medium">处理建议：</span>
          {failure.suggestion}
        </p>
      ) : null}
      <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
        <RecordDetailField label="发生阶段">
          {failureStageLabel[failure?.stage || ""] || failure?.stage || "未记录"}
        </RecordDetailField>
        <RecordDetailField label="失败代码">
          {attempt.failureReason?.code || attempt.terminalReason || "unknown"}
        </RecordDetailField>
        <RecordDetailField label="详细代码">{reason.detailCode || "-"}</RecordDetailField>
        {reason.providerCode ? (
          <RecordDetailField label="网关代码">{reason.providerCode}</RecordDetailField>
        ) : null}
        {failure?.code ? (
          <RecordDetailField label="诊断代码">{failure.code}</RecordDetailField>
        ) : null}
        {failure?.technicalMessage ? (
          <RecordDetailField label="技术错误">{failure.technicalMessage}</RecordDetailField>
        ) : null}
        <RecordDetailField label="接入任务 ID">{attempt.id}</RecordDetailField>
      </dl>
    </section>
  );
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

function intakeTypeLabel(value: string) {
  return value === "reauthentication" ? "重新认证" : "首次绑定";
}

function networkSourceLabel(value?: string | null) {
  return {
    cloudflare: "Cloudflare",
    proxy: "反向代理",
    peer: "直接连接",
  }[value || ""] || "未采集";
}

function IntakeRecordDetail({
  attempt,
  onCopyLanding,
}: {
  attempt: IntakeAttempt;
  onCopyLanding: (value: string) => void;
}) {
  const recordData: Record<string, unknown> = {
    requestContext: attempt.requestContext || {},
    routing: {
      routeVersion: attempt.routeVersion ?? null,
      syncPolicyVersion: attempt.syncPolicyVersion ?? null,
      protocolNodeId: attempt.protocol?.id || null,
      accountGroupId: attempt.group?.id || null,
    },
    result: {
      status: attempt.status,
      terminalReason: attempt.terminalReason || null,
      providerCode: attempt.providerCode || null,
      failureDetail: attempt.failureDetail || null,
    },
  };

  return (
    <div className="flex flex-col gap-5">
      <RecordDetailSummaryGrid>
        <RecordDetailSummaryCard label="接入状态">
          <div className="mt-2">{attemptBadge(attempt.status)}</div>
          <span className="mt-1 block text-xs text-muted-foreground">{attempt.status}</span>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="接入类型">
          <strong className="mt-1 block text-lg">{intakeTypeLabel(attempt.attemptType)}</strong>
          <span className="text-xs text-muted-foreground">{attempt.attemptType}</span>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="发起时间">
          <strong className="mt-1 block text-base">{formatDateTime(attempt.createdAt)}</strong>
        </RecordDetailSummaryCard>
        <RecordDetailSummaryCard label="入池结果">
          <div className="mt-2">{admissionBadge(attempt.account.admissionStatus)}</div>
          <span className="mt-1 block text-xs text-muted-foreground">
            {attempt.account.admissionStatus}
          </span>
        </RecordDetailSummaryCard>
      </RecordDetailSummaryGrid>

      <FailureDiagnosisCard attempt={attempt} />

      <div className="grid gap-3 lg:grid-cols-2">
        <RecordDetailSection title="推广信息" icon={RouteIcon}>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="落地页">
              {attempt.landing?.hostname || "内部访问地址"}
            </RecordDetailField>
            <RecordDetailField label="渠道">
              {attempt.channel?.name || "渠道已删除"}
            </RecordDetailField>
            <RecordDetailField label="模板">
              {attempt.template
                ? `${attempt.template.name} · v${attempt.template.version || "-"}`
                : "模板已删除"}
            </RecordDetailField>
          </dl>
        </RecordDetailSection>

        <RecordDetailSection title="账号信息" icon={UserRoundIcon}>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="号码">
              {formatPhoneDisplay(attempt.account.phone)}
            </RecordDetailField>
            <RecordDetailField label="账号 ID">{attempt.account.id}</RecordDetailField>
            <RecordDetailField label="号码国家">
              {attempt.account.countryCode ? (
                <CountryDisplay code={attempt.account.countryCode} className="justify-start" />
              ) : "未采集"}
            </RecordDetailField>
            <RecordDetailField label="协议">
              {attempt.protocol?.name || "协议不可用"}
            </RecordDetailField>
            <RecordDetailField label="分组">{attempt.group?.name || "未分组"}</RecordDetailField>
          </dl>
        </RecordDetailSection>

        <RecordDetailSection title="网络信息" icon={Globe2Icon} wide>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-sm">
            <RecordDetailField label="访问 IP">{attempt.sourceIp || "未采集"}</RecordDetailField>
            <RecordDetailField label="访问国家">
              {attempt.visitorCountryCode ? (
                <CountryDisplay code={attempt.visitorCountryCode} className="justify-start" />
              ) : "未采集"}
            </RecordDetailField>
            <RecordDetailField label="采集来源">
              {networkSourceLabel(attempt.networkSource)}
            </RecordDetailField>
          </dl>
        </RecordDetailSection>
      </div>

      <RecordDetailSection title="记录信息">
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-sm">
          <RecordDetailField label="记录 ID">{attempt.id}</RecordDetailField>
          <RecordDetailField label="访客 ID">{attempt.visitorId || "未提供"}</RecordDetailField>
          <RecordDetailField label="内部公开标识">{attempt.publicId || "-"}</RecordDetailField>
          <RecordDetailField label="路由版本">{attempt.routeVersion ?? "-"}</RecordDetailField>
          <RecordDetailField label="同步策略版本">
            {attempt.syncPolicyVersion ?? "-"}
          </RecordDetailField>
        </dl>
      </RecordDetailSection>

      {attempt.landing ? (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => window.open(attempt.landing?.url, "_blank", "noopener,noreferrer")}
          >
            <ExternalLinkIcon size={16} />打开落地页
          </Button>
          <Button variant="outline" onClick={() => onCopyLanding(attempt.landing?.url || "")}>
            <CopyIcon size={16} />复制落地页
          </Button>
        </div>
      ) : null}

      <RecordDataSection
        data={recordData}
        description="仅展示服务端已安全留存的请求上下文和本次处理快照，不包含验证码、代理凭据、令牌或完整请求体。"
        emptyTitle="暂无请求记录"
        emptyDescription="这条接入记录没有留存可展示的请求上下文。"
      />
    </div>
  );
}

export function AccountIntakePage() {
  const [rows, setRows] = useState<IntakeAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [pairingTypeFilter, setPairingTypeFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [templateFilter, setTemplateFilter] = useState("");
  const [protocolFilter, setProtocolFilter] = useState("");
  const [sourceIpInput, setSourceIpInput] = useState("");
  const [sourceIpFilter, setSourceIpFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [visitorCountryFilter, setVisitorCountryFilter] = useState("");
  const [admissionFilter, setAdmissionFilter] = useState("");
  const [metadataFilter, setMetadataFilter] = useState("");
  const [groups, setGroups] = useState<IntakeFilterOption[]>([]);
  const [channels, setChannels] = useState<IntakeFilterOption[]>([]);
  const [templates, setTemplates] = useState<IntakeFilterOption[]>([]);
  const [protocols, setProtocols] = useState<IntakeFilterOption[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [visitorCountries, setVisitorCountries] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<IntakeSortBy>("createdAt");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [selectedAttempt, setSelectedAttempt] = useState<IntakeAttempt | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: String(pageSize),
      });
      if (query) params.set("keyword", query);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (pairingTypeFilter) params.set("pairingType", pairingTypeFilter);
      if (groupFilter) params.set("groupId", groupFilter);
      if (channelFilter) params.set("channelId", channelFilter);
      if (templateFilter) params.set("templateId", templateFilter);
      if (protocolFilter) params.set("protocolId", protocolFilter);
      if (sourceIpFilter) params.set("sourceIp", sourceIpFilter);
      if (countryFilter) params.set("countryCode", countryFilter);
      if (visitorCountryFilter) params.set("visitorCountryCode", visitorCountryFilter);
      if (admissionFilter) params.set("admissionStatus", admissionFilter);
      if (metadataFilter) params.set("metadataStatus", metadataFilter);
      params.set("sortBy", sortBy);
      params.set("sortOrder", sortOrder);
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
  }, [admissionFilter, channelFilter, countryFilter, groupFilter, metadataFilter, page, pageSize, pairingTypeFilter, protocolFilter, query, sortBy, sortOrder, sourceIpFilter, statusFilter, templateFilter, visitorCountryFilter]);

  useEffect(() => void load(), [load]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSourceIpFilter(sourceIpInput.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [sourceIpInput]);
  useEffect(() => {
    void apiRequest("/api/personal-accounts/intake/attempts/filter-options")
      .then((payload) => {
        const data = ((payload as { data?: unknown }).data || payload) as Record<string, unknown>;
        const options = (key: string) =>
          (Array.isArray(data[key]) ? data[key] : [])
            .map((input) => {
              const row = input as Record<string, unknown>;
              return { id: snowflakeId(row, "id"), name: field(row, "name") };
            })
            .filter((row) => row.id);
        setGroups(options("groups"));
        setChannels(options("channels"));
        setTemplates(options("templates"));
        setProtocols(options("protocols"));
        setCountries(Array.isArray(data.countries) ? data.countries.map(String).filter(Boolean) : []);
        setVisitorCountries(Array.isArray(data.visitorCountries) ? data.visitorCountries.map(String).filter(Boolean) : []);
      })
      .catch(() => {
        setGroups([]);
        setChannels([]);
        setTemplates([]);
        setProtocols([]);
        setCountries([]);
        setVisitorCountries([]);
      });
  }, []);

  function changeSort(nextSortBy: IntakeSortBy, nextSortOrder: ListSortOrder) {
    setSortBy(nextSortBy);
    setSortOrder(nextSortOrder);
    setPage(1);
  }

  async function copyLandingUrl(value: string, notifications = toast) {
    try {
      await navigator.clipboard.writeText(value);
      notifications.success("访问地址已复制");
    } catch {
      notifications.error("复制失败，请手动复制");
    }
  }
  const advancedFilterCount = [
    groupFilter,
    channelFilter,
    templateFilter,
    protocolFilter,
    sourceIpFilter,
    countryFilter,
    visitorCountryFilter,
    admissionFilter,
    metadataFilter,
  ].filter(Boolean).length;

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
        filters={<>
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
          <SelectField
            ariaLabel="接入类型"
            className="w-[145px]"
            value={pairingTypeFilter}
            onValueChange={(value) => { setPairingTypeFilter(value); setPage(1); }}
            placeholder="全部接入类型"
            clearable
            options={[
              { value: "initial", label: "首次绑定" },
              { value: "reauthentication", label: "重新认证" },
            ]}
          />
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">
                <SlidersHorizontalIcon size={16} />更多筛选
                {advancedFilterCount ? <Badge tone="neutral">{advancedFilterCount}</Badge> : null}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 space-y-3">
              <SearchableSelect ariaLabel="分组筛选" value={groupFilter} onValueChange={(value) => { setGroupFilter(value); setPage(1); }} placeholder="全部分组" searchPlaceholder="搜索分组名称或 ID" options={[{ value: "", label: "全部分组" }, { value: "__ungrouped__", label: "未分组" }, ...groups.map((row) => ({ value: row.id, label: `${row.name} · ${row.id}` }))]} />
              <SearchableSelect ariaLabel="渠道筛选" value={channelFilter} onValueChange={(value) => { setChannelFilter(value); setPage(1); }} placeholder="全部渠道" searchPlaceholder="搜索渠道名称或 ID" options={[{ value: "", label: "全部渠道" }, ...channels.map((row) => ({ value: row.id, label: `${row.name} · ${row.id}` }))]} />
              <SearchableSelect ariaLabel="模板筛选" value={templateFilter} onValueChange={(value) => { setTemplateFilter(value); setPage(1); }} placeholder="全部模板" searchPlaceholder="搜索模板名称或 ID" options={[{ value: "", label: "全部模板" }, ...templates.map((row) => ({ value: row.id, label: `${row.name} · ${row.id}` }))]} />
              <SearchableSelect ariaLabel="协议筛选" value={protocolFilter} onValueChange={(value) => { setProtocolFilter(value); setPage(1); }} placeholder="全部协议" searchPlaceholder="搜索协议名称或 ID" options={[{ value: "", label: "全部协议" }, ...protocols.map((row) => ({ value: row.id, label: `${row.name} · ${row.id}` }))]} />
              <label className="field"><span>访问 IP</span><Input value={sourceIpInput} onChange={(event) => setSourceIpInput(event.target.value)} placeholder="输入完整或部分 IP" /></label>
              <SelectField ariaLabel="号码国家筛选" value={countryFilter} onValueChange={(value) => { setCountryFilter(value); setPage(1); }} placeholder="全部号码国家" clearable options={countries.map((value) => ({ value, label: value }))} />
              <SelectField ariaLabel="访问国家筛选" value={visitorCountryFilter} onValueChange={(value) => { setVisitorCountryFilter(value); setPage(1); }} placeholder="全部访问国家" clearable options={visitorCountries.map((value) => ({ value, label: value }))} />
              <SelectField ariaLabel="入池结果筛选" value={admissionFilter} onValueChange={(value) => { setAdmissionFilter(value); setPage(1); }} placeholder="全部入池结果" clearable options={[{ value: "active", label: "已正式入池" }, { value: "reserved", label: "接入预留" }, { value: "abandoned", label: "未进入账号池" }]} />
              <SelectField ariaLabel="资料同步筛选" value={metadataFilter} onValueChange={(value) => { setMetadataFilter(value); setPage(1); }} placeholder="全部资料同步状态" clearable options={[{ value: "pending", label: "待同步" }, { value: "syncing", label: "同步中" }, { value: "ready", label: "同步完成" }, { value: "failed", label: "同步失败" }, { value: "unsupported", label: "不支持同步" }]} />
              <Button variant="outline" className="w-full" disabled={!advancedFilterCount} onClick={() => { setGroupFilter(""); setChannelFilter(""); setTemplateFilter(""); setProtocolFilter(""); setSourceIpInput(""); setSourceIpFilter(""); setCountryFilter(""); setVisitorCountryFilter(""); setAdmissionFilter(""); setMetadataFilter(""); setPage(1); }}>清除精细筛选</Button>
            </PopoverContent>
          </Popover>
        </>}
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
          <Table layout="list">
            <TableHeader><TableRow>
              <ListSortableHead sortKey="accountId" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort} adaptive>号码/账号ID</ListSortableHead>
              <TableHead className="text-center">分组</TableHead>
              <ListSortableHead sortKey="status" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>接入状态</ListSortableHead>
              <ListSortableHead sortKey="pairingType" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>接入类型</ListSortableHead>
              <ListSortableHead sortKey="countryCode" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>号码国家</ListSortableHead>
              <ListSortableHead sortKey="visitorCountryCode" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>访问国家</ListSortableHead>
              <TableHead className="text-center">访问 IP</TableHead>
              <TableHead className="text-center">落地页</TableHead>
              <ListSortableHead sortKey="channelId" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>渠道</ListSortableHead>
              <TableHead className="text-center">模板</TableHead>
              <TableHead className="text-center">协议</TableHead>
              <ListSortableHead sortKey="admissionStatus" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>入池结果</ListSortableHead>
              <ListSortableHead sortKey="metadataStatus" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>资料同步</ListSortableHead>
              <ListSortableHead sortKey="createdAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>记录时间</ListSortableHead>
              <TableHead className="text-center">操作</TableHead>
            </TableRow></TableHeader>
            <TableBody>{rows.map((row) => {
              const failure = attemptFailureReason(row);
              return (
              <TableRow key={row.id}>
                <TableCell className="text-center align-middle">
                  <div className="cell-main mx-auto min-w-[210px] justify-items-center text-center">
                    <strong>{formatPhoneDisplay(row.account.phone) || row.account.name}</strong>
                    <span title={row.account.id}>{row.account.id}</span>
                  </div>
                </TableCell>
                <TableCell className="text-center align-middle">
                  <span className="whitespace-nowrap">{row.group?.name || "未分组"}</span>
                </TableCell>
                <TableCell className="text-center align-middle">
                  <div className="flex min-w-[150px] flex-col items-center gap-1 text-center">
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
                        {!row.failureDetail && failure.providerCode
                          ? ` · 提供方 ${failure.providerCode}`
                          : ""}
                      </span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-center align-middle">
                  <Badge tone="neutral">
                    {row.attemptType === "reauthentication" ? "重新认证" : "首次绑定"}
                  </Badge>
                </TableCell>
                <TableCell className="text-center align-middle">
                  {row.account.countryCode ? (
                    <CountryDisplay code={row.account.countryCode} />
                  ) : "-"}
                </TableCell>
                <TableCell className="text-center align-middle">
                  {row.visitorCountryCode ? (
                    <CountryDisplay code={row.visitorCountryCode} />
                  ) : "-"}
                </TableCell>
                <TableCell className="text-center align-middle tabular-nums">
                  <span className="whitespace-nowrap">{row.sourceIp || "-"}</span>
                </TableCell>
                <TableCell className="text-center align-middle">
                  {row.landing && row.channel ? (
                    <MonitoringLandingCell
                      hostname={row.landing.hostname}
                      url={row.landing.url}
                      slug={row.channel.slug}
                      onCopy={(value) => void copyLandingUrl(value)}
                    />
                  ) : "-"}
                </TableCell>
                <TableCell className="text-center align-middle">
                  <div className="cell-main mx-auto min-w-[140px] justify-items-center text-center">
                    <strong>{row.channel?.name || "渠道已删除"}</strong>
                    <span>{row.channel?.id || "-"}</span>
                  </div>
                </TableCell>
                <TableCell className="text-center align-middle">
                  {row.template ? (
                    <div className="cell-main mx-auto min-w-[145px] justify-items-center text-center">
                      <strong>{row.template.name}</strong>
                      <span>v{row.template.version || "-"}</span>
                    </div>
                  ) : "模板已删除"}
                </TableCell>
                <TableCell className="text-center align-middle">
                  <div className="cell-main mx-auto min-w-[145px] justify-items-center text-center">
                    <strong>{row.protocol?.name || "协议不可用"}</strong>
                    <span>{row.protocol?.id || "-"}</span>
                  </div>
                </TableCell>
                <TableCell className="text-center align-middle">
                  {admissionBadge(row.account.admissionStatus)}
                </TableCell>
                <TableCell className="text-center align-middle">
                  <Badge tone={row.account.metadataSyncStatus === "ready" ? "success" : row.account.metadataSyncStatus === "failed" ? "danger" : row.account.metadataSyncStatus === "syncing" ? "warning" : "neutral"}>
                    {row.account.metadataSyncStatus === "ready" ? "同步完成" : row.account.metadataSyncStatus === "failed" ? "同步失败" : row.account.metadataSyncStatus === "syncing" ? "同步中" : row.account.metadataSyncStatus === "unsupported" ? "不支持同步" : "待同步"}
                  </Badge>
                </TableCell>
                <TableCell className="text-center align-middle text-muted-foreground">
                  <span className="whitespace-nowrap">{formatDateTime(row.createdAt)}</span>
                </TableCell>
                <TableCell className="text-center align-middle">
                  <Button variant="outline" size="sm" onClick={() => setSelectedAttempt(row)}>
                    查看详情
                  </Button>
                </TableCell>
              </TableRow>
              );
            })}</TableBody>
          </Table>
        ) : (
          <EmptyState title="暂无接入记录" description="访客从渠道落地页发起首次绑定或重新认证后，会显示在这里。" />
        )}
      </ListTableCard>
      <Drawer
        open={Boolean(selectedAttempt)}
        onClose={() => setSelectedAttempt(null)}
        title={`接入详情${selectedAttempt ? ` · ${selectedAttempt.id}` : ""}`}
        description={
          selectedAttempt
            ? `${attemptLabel[selectedAttempt.status] || selectedAttempt.status} · ${formatDateTime(selectedAttempt.createdAt)}`
            : ""
        }
        wide
        footer={<Button onClick={() => setSelectedAttempt(null)}>关闭</Button>}
      >
        {selectedAttempt ? (
          <IntakeRecordDetail
            attempt={selectedAttempt}
            onCopyLanding={(value) => void copyLandingUrl(value, toast)}
          />
        ) : null}
      </Drawer>
    </StandardListPage>
  );
}
