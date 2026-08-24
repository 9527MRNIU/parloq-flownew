import {
  ArrowDownToLineIcon,
  ArrowUpFromLineIcon,
  LoaderCircleIcon,
  NetworkIcon,
  PlusIcon,
  RefreshCwIcon,
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
import { EntityPrimaryCell } from "../components/entity-primary-cell";
import {
  DrawerFieldLabel,
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";
import {
  Badge,
  Button,
  Checkbox,
  confirmAction,
  Drawer,
  EmptyState,
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
  Textarea,
  toast,
} from "../components/ui";

const COOLDOWN_KEY = "parloq-protocol-batch-cooldown-until";

type ProtocolNode = {
  id: string;
  readKey: string;
  name: string;
  ingressEnabled: boolean;
  marketingEnabled: boolean;
  online: boolean;
  healthStatus: "available" | "capacity_limited" | "offline";
  healthReason: string;
  totalCount: number | null;
  validCount: number | null;
  validRate: number | null;
  onlineCount: number | null;
  onlineRate: number | null;
  remark: string;
  activePairingCount: number;
  maxAccountCount: number | null;
  maxOnlineAccounts: number | null;
  maxConcurrentPairings: number | null;
  connectionPolicy: "on_demand" | "always_on";
  idleDisconnectSeconds: number;
  postVerifyGraceSeconds: number;
  syncPolicy: SyncPolicy;
  rateLimitPolicy: RateLimitPolicy;
  createdAt: string;
};

type SyncPolicy = {
  avatar: boolean;
  profileStatus: boolean;
  businessProfile: boolean;
  groupSummary: boolean;
  groupDetails: boolean;
  contacts: boolean;
  chats: boolean;
  messageHistory: boolean;
  privacySettings: boolean;
  blocklist: boolean;
};

type RateLimitRule = {
  maxRequests: number | null;
  windowSeconds: number;
};

type RateLimitPolicy = {
  visitorCheck: RateLimitRule;
  visitorAttempt: RateLimitRule;
  ipStart: RateLimitRule;
  phoneAttempt: RateLimitRule;
  channelAttempt: RateLimitRule;
  status: RateLimitRule;
  cancel: RateLimitRule;
};

type RateLimitPolicyForm = {
  [Key in keyof RateLimitPolicy]: {
    maxRequests: string;
    windowSeconds: string;
  };
};

type ProtocolPool = {
  id: string;
  name: string;
  remark: string;
  members: Array<{
    protocolNodeId: string;
    protocolNodeName: string;
    priority: number;
    enabled: boolean;
    available: boolean;
  }>;
};

const DEFAULT_SYNC_POLICY: SyncPolicy = {
  avatar: true,
  profileStatus: true,
  businessProfile: true,
  groupSummary: true,
  groupDetails: false,
  contacts: false,
  chats: false,
  messageHistory: false,
  privacySettings: false,
  blocklist: false,
};

const DEFAULT_RATE_LIMIT_POLICY: RateLimitPolicy = {
  visitorCheck: { maxRequests: 5, windowSeconds: 600 },
  visitorAttempt: { maxRequests: 5, windowSeconds: 600 },
  ipStart: { maxRequests: 5, windowSeconds: 600 },
  phoneAttempt: { maxRequests: 5, windowSeconds: 600 },
  channelAttempt: { maxRequests: null, windowSeconds: 60 },
  status: { maxRequests: 60, windowSeconds: 60 },
  cancel: { maxRequests: 5, windowSeconds: 600 },
};

const RATE_LIMIT_FIELDS: Array<[
  keyof RateLimitPolicy,
  string,
  string,
]> = [
  ["visitorCheck", "指纹配对检查", "同一渠道、同一设备指纹每次调用开始配对接口都会计数，无论是否创建新任务。"],
  ["ipStart", "IP 配对检查", "同一渠道、同一来源 IP 每次调用开始配对接口都会计数，无论是否创建新任务。"],
  ["visitorAttempt", "指纹新建任务", "同一渠道、同一设备指纹准备创建新配对任务时计数；继续已有任务不计数。"],
  ["phoneAttempt", "号码新建任务", "同一租户、同一号码创建新配对任务时计数；继续已有任务不计数。"],
  ["channelAttempt", "渠道新建任务", "单个渠道在统计窗口内累计创建的新配对任务数；继续已有任务不计数，也不同于协议节点同时进行的配对任务上限。"],
  ["status", "任务状态查询", "按同一个配对任务限制状态查询频率。"],
  ["cancel", "任务取消请求", "按同一个配对任务限制取消请求频率。"],
];

function toRateLimitForm(policy: RateLimitPolicy): RateLimitPolicyForm {
  return Object.fromEntries(
    Object.entries(policy).map(([key, rule]) => [
      key,
      {
        maxRequests: rule.maxRequests == null ? "" : String(rule.maxRequests),
        windowSeconds: String(rule.windowSeconds),
      },
    ]),
  ) as RateLimitPolicyForm;
}

function validRateLimitForm(policy: RateLimitPolicyForm) {
  return Object.entries(policy).every(([key, rule]) => {
    const unlimitedChannel =
      key === "channelAttempt" && rule.maxRequests.trim() === "";
    return (
      (unlimitedChannel ||
        (Number.isInteger(Number(rule.maxRequests)) &&
          Number(rule.maxRequests) >= 1 &&
          Number(rule.maxRequests) <= 100_000)) &&
      Number.isInteger(Number(rule.windowSeconds)) &&
      Number(rule.windowSeconds) >= 1 &&
      Number(rule.windowSeconds) <= 86_400
    );
  });
}

const value = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return row[key];
  return undefined;
};
const text = (row: Record<string, unknown>, ...keys: string[]) => {
  const found = value(row, ...keys);
  return found == null ? "" : String(found);
};
const number = (row: Record<string, unknown>, ...keys: string[]) => {
  const found = value(row, ...keys);
  if (found == null || found === "") return null;
  const parsed = Number(found);
  return Number.isFinite(parsed) ? parsed : null;
};
const boolean = (
  row: Record<string, unknown>,
  fallback: boolean,
  ...keys: string[]
) => {
  const found = value(row, ...keys);
  if (found == null) return fallback;
  if (typeof found === "string")
    return ["true", "1", "enabled", "on"].includes(found.toLowerCase());
  return Boolean(found);
};
function normalizeRate(explicit: number | null, count: number | null, total: number | null) {
  if (explicit != null) return explicit <= 1 ? explicit * 100 : explicit;
  if (count == null || total == null || total <= 0) return null;
  return (count / total) * 100;
}
function protocolNode(input: unknown): ProtocolNode {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  const totalCount = number(row, "totalCount", "total_count", "accountTotal", "account_total", "accountCount", "account_count");
  const validCount = number(row, "validCount", "valid_count", "validAccounts", "valid_accounts", "effectiveCount", "effective_count");
  const onlineCount = number(row, "onlineCount", "online_count", "onlineAccounts", "online_accounts");
  const rawSync = (value(row, "syncPolicy", "sync_policy") || {}) as Record<string, unknown>;
  const rawRatePolicy = (value(row, "rateLimitPolicy", "rate_limit_policy") || {}) as Record<string, unknown>;
  return {
    id,
    readKey: entityRowKey(row, id, "protocol-node", `${text(row, "name", "title")}:${text(row, "createdAt", "created_at")}`),
    name: text(row, "name", "title"),
    ingressEnabled: boolean(row, true, "ingressEnabled", "ingress_enabled", "accountIngressEnabled", "account_ingress_enabled", "allowIngress", "allow_ingress"),
    marketingEnabled: boolean(row, true, "marketingEnabled", "marketing_enabled", "allowMarketing", "allow_marketing"),
    online: boolean(row, true, "online", "onlineEnabled", "online_enabled"),
    healthStatus: (text(row, "healthStatus", "health_status") || "offline") as ProtocolNode["healthStatus"],
    healthReason: text(row, "healthReason", "health_reason"),
    totalCount,
    validCount,
    validRate: normalizeRate(number(row, "validRate", "valid_rate", "effectiveRate", "effective_rate"), validCount, totalCount),
    onlineCount,
    onlineRate: normalizeRate(number(row, "onlineRate", "online_rate"), onlineCount, validCount),
    remark: text(row, "remark", "note", "description"),
    activePairingCount: number(row, "activePairingCount", "active_pairing_count") || 0,
    maxAccountCount: number(row, "maxAccountCount", "max_account_count"),
    maxOnlineAccounts: number(row, "maxOnlineAccounts", "max_online_accounts"),
    maxConcurrentPairings: number(row, "maxConcurrentPairings", "max_concurrent_pairings"),
    connectionPolicy: (text(row, "connectionPolicy", "connection_policy") || "on_demand") as ProtocolNode["connectionPolicy"],
    idleDisconnectSeconds: number(row, "idleDisconnectSeconds", "idle_disconnect_seconds") || 600,
    postVerifyGraceSeconds: number(row, "postVerifyGraceSeconds", "post_verify_grace_seconds") ?? 120,
    syncPolicy: Object.fromEntries(
      Object.entries(DEFAULT_SYNC_POLICY).map(([key, fallback]) => [
        key,
        typeof rawSync[key] === "boolean" ? rawSync[key] : fallback,
      ]),
    ) as SyncPolicy,
    rateLimitPolicy: Object.fromEntries(
      Object.entries(DEFAULT_RATE_LIMIT_POLICY).map(([key, fallback]) => {
        const rawRule = (rawRatePolicy[key] || {}) as Record<string, unknown>;
        return [
          key,
          {
            maxRequests: number(rawRule, "maxRequests", "max_requests") ?? fallback.maxRequests,
            windowSeconds: number(rawRule, "windowSeconds", "window_seconds") ?? fallback.windowSeconds,
          },
        ];
      }),
    ) as RateLimitPolicy,
    createdAt: text(row, "createdAt", "created_at"),
  };
}
function protocolPool(input: unknown): ProtocolPool {
  const row = input as Record<string, unknown>;
  const rawMembers = Array.isArray(row.members) ? row.members : [];
  return {
    id: snowflakeId(row, "id"),
    name: text(row, "name"),
    remark: text(row, "remark"),
    members: rawMembers.map((inputMember) => {
      const member = inputMember as Record<string, unknown>;
      return {
        protocolNodeId: snowflakeId(member, "protocolNodeId", "protocol_node_id"),
        protocolNodeName: text(member, "protocolNodeName", "protocol_node_name"),
        priority: number(member, "priority") || 100,
        enabled: boolean(member, true, "enabled"),
        available: boolean(member, false, "available"),
      };
    }),
  };
}
function rateBadge(rate: number | null, kind: "valid" | "online") {
  if (rate == null) return <span className="text-muted-foreground">-</span>;
  const good = kind === "valid" ? rate >= 80 : rate >= 50;
  const warning = kind === "valid" ? rate >= 50 : rate >= 20;
  return (
    <Badge tone={good ? "success" : warning ? "warning" : "danger"}>
      {rate.toFixed(1)}%
    </Badge>
  );
}

export function ProtocolManagementPage() {
  const { can } = useAuth();
  const canManage = can("resources.protocol.manage") || can("resources.ip.manage");
  const [rows, setRows] = useState<ProtocolNode[]>([]);
  const [pools, setPools] = useState<ProtocolPool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<ProtocolNode | null>(null);
  const [creating, setCreating] = useState(false);
  const [interfaceSpec, setInterfaceSpec] = useState<Record<string, unknown> | null>(null);
  const [specLoading, setSpecLoading] = useState(false);
  const [poolEditing, setPoolEditing] = useState<ProtocolPool | "new" | null>(null);
  const [poolSaving, setPoolSaving] = useState(false);
  const [poolForm, setPoolForm] = useState({ name: "", remark: "", memberIds: [] as string[] });
  const [form, setForm] = useState({
    name: "",
    ingressEnabled: true,
    marketingEnabled: true,
    maxAccountCount: "",
    maxOnlineAccounts: "1000",
    maxConcurrentPairings: "",
    connectionPolicy: "on_demand" as "on_demand" | "always_on",
    idleDisconnectSeconds: "600",
    postVerifyGraceSeconds: "120",
    syncPolicy: { ...DEFAULT_SYNC_POLICY },
    rateLimitPolicy: toRateLimitForm(DEFAULT_RATE_LIMIT_POLICY),
    remark: "",
  });
  const [saving, setSaving] = useState(false);
  const [batching, setBatching] = useState<"connect" | "disconnect" | "">("");
  const [cooldownUntil, setCooldownUntil] = useState(
    () => Number(window.localStorage.getItem(COOLDOWN_KEY) || 0),
  );
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [payload, poolPayload] = await Promise.all([
        apiRequest("/api/protocol-nodes?pageSize=100"),
        apiRequest("/api/protocol-pools?pageSize=100"),
      ]);
      const nextRows = unwrapList<unknown>(payload).rows.map(protocolNode);
      setRows(nextRows);
      setPools(unwrapList<unknown>(poolPayload).rows.map(protocolPool));
      setSelected((current) => current.filter((id) => nextRows.some((row) => row.id === id)));
    } catch (caught) {
      setRows([]);
      setPools([]);
      setError(caught instanceof Error ? caught.message : "协议节点加载失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => void load(), [load]);
  useEffect(() => {
    if (cooldownUntil <= Date.now()) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [cooldownUntil]);

  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) => `${row.id} ${row.name} ${row.remark}`.toLowerCase().includes(search))
      : rows;
  }, [keyword, rows]);
  const nodePagination = useClientPagination(visible, { resetKey: keyword });
  const poolPagination = useClientPagination(pools);
  const visibleIds = visible.map((row) => row.id).filter(Boolean);
  const allVisibleSelected = Boolean(visibleIds.length) && visibleIds.every((id) => selected.includes(id));
  const remainingSeconds = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));

  function openEdit(row: ProtocolNode) {
    setCreating(false);
    setEditing(row);
    setForm({
      name: row.name,
      ingressEnabled: row.ingressEnabled,
      marketingEnabled: row.marketingEnabled,
      maxAccountCount: row.maxAccountCount == null ? "" : String(row.maxAccountCount),
      maxOnlineAccounts: row.maxOnlineAccounts == null ? "" : String(row.maxOnlineAccounts),
      maxConcurrentPairings: row.maxConcurrentPairings == null ? "" : String(row.maxConcurrentPairings),
      connectionPolicy: row.connectionPolicy,
      idleDisconnectSeconds: String(row.idleDisconnectSeconds),
      postVerifyGraceSeconds: String(row.postVerifyGraceSeconds),
      syncPolicy: { ...row.syncPolicy },
      rateLimitPolicy: toRateLimitForm(row.rateLimitPolicy),
      remark: row.remark,
    });
  }
  function openCreate() {
    setEditing(null);
    setCreating(true);
    setForm({
      name: "",
      ingressEnabled: true,
      marketingEnabled: true,
      maxAccountCount: "",
      maxOnlineAccounts: "1000",
      maxConcurrentPairings: "",
      connectionPolicy: "on_demand",
      idleDisconnectSeconds: "600",
      postVerifyGraceSeconds: "120",
      syncPolicy: { ...DEFAULT_SYNC_POLICY },
      rateLimitPolicy: toRateLimitForm(DEFAULT_RATE_LIMIT_POLICY),
      remark: "",
    });
  }
  async function save() {
    if ((!creating && !editing?.id) || !form.name.trim()) return;
    setSaving(true);
    try {
      await apiRequest(creating ? "/api/protocol-nodes" : `/api/protocol-nodes/${editing?.id}`, {
        method: creating ? "POST" : "PATCH",
        body: JSON.stringify({
          name: form.name.trim(),
          ingressEnabled: form.ingressEnabled,
          marketingEnabled: form.marketingEnabled,
          maxAccountCount: form.maxAccountCount === "" ? null : Number(form.maxAccountCount),
          maxOnlineAccounts: form.maxOnlineAccounts === "" ? null : Number(form.maxOnlineAccounts),
          maxConcurrentPairings: form.maxConcurrentPairings === "" ? null : Number(form.maxConcurrentPairings),
          connectionPolicy: form.connectionPolicy,
          idleDisconnectSeconds: Number(form.idleDisconnectSeconds),
          postVerifyGraceSeconds: Number(form.postVerifyGraceSeconds),
          syncPolicy: form.syncPolicy,
          rateLimitPolicy: Object.fromEntries(
            Object.entries(form.rateLimitPolicy).map(([key, rule]) => [
              key,
              {
                maxRequests: rule.maxRequests.trim() === "" ? null : Number(rule.maxRequests),
                windowSeconds: Number(rule.windowSeconds),
              },
            ]),
          ),
          remark: form.remark.trim() || null,
        }),
      });
      setEditing(null);
      setCreating(false);
      await load();
      toast.success(creating ? "协议节点已创建" : "协议设置已保存");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  async function openSpec(row: ProtocolNode) {
    setSpecLoading(true);
    try {
      const payload = await apiRequest(`/api/protocol-nodes/${row.id}/integration-spec`);
      const root = payload as Record<string, unknown>;
      setInterfaceSpec((root.data || root) as Record<string, unknown>);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "接口规范加载失败");
    } finally {
      setSpecLoading(false);
    }
  }
  async function removeNode(row: ProtocolNode) {
    if (!(await confirmAction({ title: `删除协议“${row.name}”？`, description: "删除后无法恢复；仍有账号、渠道或协议池引用时系统会拒绝。", confirmText: "确认删除", destructive: true }))) return;
    try {
      await apiRequest(`/api/protocol-nodes/${row.id}`, { method: "DELETE" });
      toast.success("协议已删除");
      await load();
    } catch (caught) { toast.error(caught instanceof Error ? caught.message : "协议删除失败"); }
  }
  function openPool(pool?: ProtocolPool) {
    setPoolEditing(pool || "new");
    setPoolForm({
      name: pool?.name || "",
      remark: pool?.remark || "",
      memberIds: pool?.members.filter((member) => member.enabled).map((member) => member.protocolNodeId) || [],
    });
  }
  async function savePool() {
    if (!poolEditing || !poolForm.name.trim() || !poolForm.memberIds.length) return;
    setPoolSaving(true);
    try {
      const creatingPool = poolEditing === "new";
      await apiRequest(creatingPool ? "/api/protocol-pools" : `/api/protocol-pools/${poolEditing.id}`, {
        method: creatingPool ? "POST" : "PATCH",
        body: JSON.stringify({
          name: poolForm.name.trim(),
          remark: poolForm.remark.trim() || null,
          members: poolForm.memberIds.map((protocolNodeId, index) => ({
            protocolNodeId,
            priority: (index + 1) * 100,
            enabled: true,
          })),
        }),
      });
      setPoolEditing(null);
      toast.success(creatingPool ? "协议池已创建" : "协议池已保存");
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "协议池保存失败");
    } finally {
      setPoolSaving(false);
    }
  }
  async function removePool(pool: ProtocolPool) {
    if (!(await confirmAction({ title: `删除协议池“${pool.name}”？`, description: "删除后无法恢复；仍被推广渠道使用的协议池不能删除。", confirmText: "确认删除", destructive: true }))) return;
    try {
      await apiRequest(`/api/protocol-pools/${pool.id}`, { method: "DELETE" });
      toast.success("协议池已删除");
      await load();
    } catch (caught) { toast.error(caught instanceof Error ? caught.message : "协议池删除失败"); }
  }
  async function batch(operation: "connect" | "disconnect") {
    if (!selected.length || remainingSeconds > 0) return;
    const label = operation === "connect" ? "上线" : "下线";
    if (!(await confirmAction({
      title: `确认将选中的 ${selected.length} 个协议批量${label}？`,
      description: operation === "connect"
        ? "系统将逐个连接这些协议下当前离线且可上线的账号。"
        : "系统将逐个断开这些协议下当前在线的账号。",
      confirmText: `批量${label}`,
    }))) return;
    setBatching(operation);
    try {
      await apiRequest(`/api/protocol-nodes/batch-${operation}`, {
        method: "POST",
        body: JSON.stringify({ protocolIds: selected }),
      });
      const until = Date.now() + 60_000;
      window.localStorage.setItem(COOLDOWN_KEY, String(until));
      setCooldownUntil(until);
      setNow(Date.now());
      toast.success(`已提交 ${selected.length} 个协议批量${label}`);
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : `批量${label}失败`);
    } finally {
      setBatching("");
    }
  }

  return (
    <StandardListPage viewport>
      <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        协议节点用于批量管控一组账号。进号开关影响后续账号接入；营销开关关闭后，该节点账号会被营销任务跳过。
      </div>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索协议名称、ID 或备注" }}
        meta={selected.length ? `已选择 ${selected.length} 个协议` : `${visible.length} 个协议`}
        actions={
          <>
            <Button disabled={!canManage} onClick={openCreate}>
              <PlusIcon size={16} />新建协议
            </Button>
            <Button
              variant="outline"
              disabled={!canManage || !selected.length || Boolean(batching) || remainingSeconds > 0}
              title={remainingSeconds ? `操作冷却中，还需等待 ${remainingSeconds} 秒` : "对选中协议下所有离线账号发起上线"}
              onClick={() => void batch("connect")}
            >
              {batching === "connect" ? <Spinner /> : <ArrowUpFromLineIcon size={16} />}
              批量上线{remainingSeconds ? ` (${remainingSeconds}s)` : ""}
            </Button>
            <Button
              variant="outline"
              disabled={!canManage || !selected.length || Boolean(batching) || remainingSeconds > 0}
              title={remainingSeconds ? `操作冷却中，还需等待 ${remainingSeconds} 秒` : "对选中协议下所有在线账号发起下线"}
              onClick={() => void batch("disconnect")}
            >
              {batching === "disconnect" ? <Spinner /> : <ArrowDownToLineIcon size={16} />}
              批量下线{remainingSeconds ? ` (${remainingSeconds}s)` : ""}
            </Button>
            <Button variant="outline" onClick={() => void load()} disabled={loading}>
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新
            </Button>
          </>
        }
      />
      <ListPagination
        page={nodePagination.page}
        pageSize={nodePagination.pageSize}
        total={nodePagination.total}
        disabled={loading}
        onPageChange={nodePagination.setPage}
        onPageSizeChange={nodePagination.setPageSize}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载协议节点…</div> : error ? (
          <div className="error-state"><strong>协议加载失败</strong><span>{error}</span><Button variant="outline" onClick={() => void load()}>重试</Button></div>
        ) : visible.length ? (
          <Table layout="list">
            <TableHeader><TableRow>
              <TableHead><Checkbox aria-label="选择全部协议" checked={allVisibleSelected} onCheckedChange={(checked) => setSelected(checked ? Array.from(new Set([...selected, ...visibleIds])) : selected.filter((id) => !visibleIds.includes(id)))} /></TableHead>
              <TableHead>协议名称</TableHead><TableHead>进号开关</TableHead><TableHead>营销开关</TableHead><TableHead>账号总量</TableHead><TableHead>有效数 / 率</TableHead><TableHead>在线数 / 率</TableHead><TableHead adaptive>备注</TableHead><TableHead>创建时间</TableHead><TableHead>操作</TableHead>
            </TableRow></TableHeader>
            <TableBody>{nodePagination.rows.map((row) => <TableRow key={row.readKey}>
              <TableCell><Checkbox aria-label={`选择协议 ${row.name || "待迁移协议"}`} disabled={!row.id} checked={Boolean(row.id) && selected.includes(row.id)} onCheckedChange={(checked) => row.id && setSelected((current) => checked ? [...current, row.id] : current.filter((id) => id !== row.id))} /></TableCell>
              <TableCell primary>
                <EntityPrimaryCell
                  title={row.name || "待迁移协议"}
                  id={row.id}
                  status={{
                    label: row.healthStatus === "available" ? "可接入" : row.healthStatus === "capacity_limited" ? "容量受限" : "不可接入",
                    description: row.healthReason || "协议节点当前可承载新的账号接入。",
                    tone: row.healthStatus === "available" ? "success" : row.healthStatus === "capacity_limited" ? "warning" : "neutral",
                    details: [
                      { label: "进号", value: row.ingressEnabled ? "已开启" : "已关闭" },
                      { label: "营销", value: row.marketingEnabled ? "已开启" : "已关闭" },
                      { label: "账号数", value: row.totalCount == null ? "-" : row.totalCount.toLocaleString() },
                      { label: "并发配对", value: row.activePairingCount.toLocaleString() },
                    ],
                  }}
                />
              </TableCell>
              <TableCell><Badge tone={row.ingressEnabled ? "success" : "neutral"}>{row.ingressEnabled ? "已开启" : "已关闭"}</Badge></TableCell>
              <TableCell><Badge tone={row.marketingEnabled ? "success" : "neutral"}>{row.marketingEnabled ? "已开启" : "已关闭"}</Badge></TableCell>
              <TableCell>{row.totalCount == null ? <span className="text-muted-foreground">-</span> : row.totalCount.toLocaleString()}</TableCell>
              <TableCell><div className="flex items-center gap-2"><span>{row.validCount == null ? "-" : row.validCount.toLocaleString()}</span>{rateBadge(row.validRate, "valid")}</div></TableCell>
              <TableCell><div className="flex items-center gap-2"><span>{row.onlineCount == null ? "-" : row.onlineCount.toLocaleString()}</span>{rateBadge(row.onlineRate, "online")}</div></TableCell>
              <TableCell><span className="block max-w-52 truncate text-muted-foreground" title={row.remark}>{row.remark || "-"}</span></TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              <TableCell><div className="flex min-w-max justify-end gap-2">
                <Button variant="outline" size="sm" disabled={!row.id || specLoading} onClick={() => void openSpec(row)}>接口规范</Button>
                {canManage ? <Button variant="outline" size="sm" disabled={!row.id} onClick={() => openEdit(row)}>编辑</Button> : null}
                {canManage ? <Button variant="destructive" size="sm" disabled={!row.id} onClick={() => void removeNode(row)}>删除</Button> : null}
              </div></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        ) : <EmptyState title="暂无协议节点" description="协议节点由系统接入配置创建，当前没有可管理的节点。" />}
      </ListTableCard>
      <div className="mt-4 flex items-center justify-between">
        <div><h2 className="text-base font-semibold">协议池回退</h2><p className="text-sm text-muted-foreground">只有渠道明确绑定协议池时才会按成员优先级回退；直接绑定节点永不自动切换。</p></div>
        <Button variant="outline" disabled={!canManage || !rows.length} onClick={() => openPool()}><NetworkIcon size={16} />新建协议池</Button>
      </div>
      <ListPagination
        ariaLabel="协议池分页"
        page={poolPagination.page}
        pageSize={poolPagination.pageSize}
        total={poolPagination.total}
        disabled={loading}
        onPageChange={poolPagination.setPage}
        onPageSizeChange={poolPagination.setPageSize}
      />
      <ListTableCard>
        {pools.length ? <Table layout="list">
          <TableHeader><TableRow><TableHead>协议池</TableHead><TableHead adaptive>回退顺序</TableHead><TableHead>备注</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
          <TableBody>{poolPagination.rows.map((pool) => <TableRow key={pool.id}>
            <TableCell><EntityPrimaryCell title={pool.name} id={pool.id} status={{ label: pool.members.some((member) => member.available) ? "可回退" : "无可用成员", description: pool.members.some((member) => member.available) ? "池中至少有一个成员可接入。" : "当前所有成员不可接入，渠道请求会明确失败。", tone: pool.members.some((member) => member.available) ? "success" : "warning" }} /></TableCell>
            <TableCell><div className="flex flex-wrap gap-1">{pool.members.map((member, index) => <Badge key={member.protocolNodeId} tone={member.available ? "success" : "neutral"}>{index + 1}. {member.protocolNodeName}</Badge>)}</div></TableCell>
            <TableCell><span className="block max-w-64 truncate text-muted-foreground">{pool.remark || "-"}</span></TableCell>
            <TableCell><div className="flex min-w-max justify-end gap-2">{canManage ? <><Button variant="outline" size="sm" onClick={() => openPool(pool)}>编辑</Button><Button variant="destructive" size="sm" onClick={() => void removePool(pool)}>删除</Button></> : null}</div></TableCell>
          </TableRow>)}</TableBody>
        </Table> : <EmptyState title="暂无协议池" description="默认拒绝不可用节点；需要回退时再显式创建协议池并绑定渠道。" />}
      </ListTableCard>
      <Drawer
        open={creating || Boolean(editing)}
        onClose={() => { if (!saving) { setEditing(null); setCreating(false); } }}
        title={creating ? "新建协议节点" : `编辑协议 · ${editing?.id || ""}`}
        description="协议节点是共享 Baileys 网关上的逻辑运营分区；容量、连接和同步设置只影响此节点。"
        footer={<><Button variant="outline" disabled={saving} onClick={() => { setEditing(null); setCreating(false); }}>取消</Button><Button disabled={saving || !form.name.trim() || form.name.trim().length > 64 || form.remark.length > 512 || Number(form.idleDisconnectSeconds) < 60 || Number(form.postVerifyGraceSeconds) < 0 || !validRateLimitForm(form.rateLimitPolicy)} onClick={() => void save()}>{saving ? <LoaderCircleIcon className="spin" size={16} /> : null}{creating ? "创建" : "保存"}</Button></>}
      >
        <DrawerFormLayout>
          <DrawerFormSection title="基础信息" hideHeader>
            <DrawerFormField label="协议名称" meta={`${form.name.length}/64`} required>
              <Input maxLength={64} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="请输入协议名称，用于识别区分不同协议" />
            </DrawerFormField>
            <DrawerFormField label="进号开关" hint="关闭后暂停新账号通过该节点接入，不影响已在线账号。">
              <Switch checked={form.ingressEnabled} onCheckedChange={(checked) => setForm((current) => ({ ...current, ingressEnabled: checked }))} aria-label="进号开关" />
            </DrawerFormField>
            <DrawerFormField label="营销开关" hint="关闭后该节点账号不会被营销任务选中，账号连接不受影响。">
              <Switch checked={form.marketingEnabled} onCheckedChange={(checked) => setForm((current) => ({ ...current, marketingEnabled: checked }))} aria-label="营销开关" />
            </DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="容量限制" description="留空表示不限制。默认总账号和并发配对不限，在线账号上限 1000。">
            <DrawerFormField label="账号总量上限"><Input type="number" min={0} value={form.maxAccountCount} onChange={(event) => setForm((current) => ({ ...current, maxAccountCount: event.target.value }))} placeholder="不限制" /></DrawerFormField>
            <DrawerFormField label="在线账号上限"><Input type="number" min={0} value={form.maxOnlineAccounts} onChange={(event) => setForm((current) => ({ ...current, maxOnlineAccounts: event.target.value }))} placeholder="不限制" /></DrawerFormField>
            <DrawerFormField label="并发配对上限"><Input type="number" min={0} value={form.maxConcurrentPairings} onChange={(event) => setForm((current) => ({ ...current, maxConcurrentPairings: event.target.value }))} placeholder="不限制" /></DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="连接策略" description="按需在线会在配对同步、发送和人工操作时持有连接租约；空闲后仅断开 Socket，不退出 WhatsApp 登录。">
            <DrawerFormField label="账号连接模式" required><SelectField className="w-full" value={form.connectionPolicy} onValueChange={(next) => setForm((current) => ({ ...current, connectionPolicy: next as "on_demand" | "always_on" }))} options={[{ value: "on_demand", label: "按需在线 (推荐)" }, { value: "always_on", label: "持续连接" }]} /></DrawerFormField>
            <DrawerFormField label="空闲断开 (秒)" required><Input type="number" min={60} max={86400} value={form.idleDisconnectSeconds} onChange={(event) => setForm((current) => ({ ...current, idleDisconnectSeconds: event.target.value }))} /></DrawerFormField>
            <DrawerFormField label="验证后保活 (秒)" required><Input type="number" min={0} max={3600} value={form.postVerifyGraceSeconds} onChange={(event) => setForm((current) => ({ ...current, postVerifyGraceSeconds: event.target.value }))} /></DrawerFormField>
          </DrawerFormSection>

          <DrawerFormSection title="公共配对风控与限速" description="设备和 IP 规则限制每次开始配对请求；设备、号码和渠道的新建规则只限制新配对任务；状态查询和取消请求按单个配对任务限制。">
            {RATE_LIMIT_FIELDS.map(([key, label, description]) => (
              <DrawerFormField key={key} label={label} hint={description} align="compound">
                <div className="grid min-w-0 grid-cols-2 gap-2">
                  <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
                    <DrawerFieldLabel required={key !== "channelAttempt"}>{key === "channelAttempt" ? "最多请求 (留空不限)" : "最多请求"}</DrawerFieldLabel>
                    <Input type="number" min={1} max={100000} placeholder={key === "channelAttempt" ? "不限制" : undefined} value={form.rateLimitPolicy[key].maxRequests} onChange={(event) => setForm((current) => ({ ...current, rateLimitPolicy: { ...current.rateLimitPolicy, [key]: { ...current.rateLimitPolicy[key], maxRequests: event.target.value } } }))} />
                  </label>
                  <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
                    <DrawerFieldLabel required={key !== "channelAttempt" || Boolean(form.rateLimitPolicy[key].maxRequests.trim())}>统计窗口 (秒)</DrawerFieldLabel>
                    <Input type="number" min={1} max={86400} disabled={key === "channelAttempt" && form.rateLimitPolicy[key].maxRequests.trim() === ""} value={form.rateLimitPolicy[key].windowSeconds} onChange={(event) => setForm((current) => ({ ...current, rateLimitPolicy: { ...current.rateLimitPolicy, [key]: { ...current.rateLimitPolicy[key], windowSeconds: event.target.value } } }))} />
                  </label>
                </div>
              </DrawerFormField>
            ))}
          </DrawerFormSection>

          <DrawerFormSection title="绑定后同步范围" description="账号基础身份始终同步；以下选项会在创建配对任务时快照，之后修改不改变进行中的配对。">
            {([
              ["avatar", "头像", "读取账号头像是否存在"],
              ["profileStatus", "资料状态", "读取 About / 状态文字"],
              ["businessProfile", "商业资料", "读取可用的 Business Profile"],
              ["groupSummary", "群组概览", "同步参与群数量"],
              ["groupDetails", "群组详情", "读取群组元数据；开启时自动包含群组概览"],
              ["contacts", "联系人", "监听并同步联系人更新"],
              ["chats", "聊天列表", "接收聊天列表同步"],
              ["messageHistory", "消息历史", "接收历史消息同步，资源开销较高"],
              ["privacySettings", "隐私设置", "读取账号隐私配置"],
              ["blocklist", "黑名单", "读取已屏蔽号码列表"],
            ] as Array<[keyof SyncPolicy, string, string]>).map(([key, label, description]) => (
              <DrawerFormField key={key} label={label} hint={description}>
                <Switch checked={form.syncPolicy[key]} onCheckedChange={(checked) => setForm((current) => ({ ...current, syncPolicy: { ...current.syncPolicy, [key]: checked, ...(key === "groupDetails" && checked ? { groupSummary: true } : {}) } }))} aria-label={`同步${label}`} />
              </DrawerFormField>
            ))}
          </DrawerFormSection>

          <DrawerFormSection title="备注">
            <DrawerFormField label="备注内容" align="start" meta={`${form.remark.length}/512`}>
              <Textarea rows={5} maxLength={512} value={form.remark} onChange={(event) => setForm((current) => ({ ...current, remark: event.target.value }))} placeholder="请输入备注，最多 512 字" />
            </DrawerFormField>
          </DrawerFormSection>
        </DrawerFormLayout>
      </Drawer>
      <Drawer
        open={Boolean(poolEditing)}
        onClose={() => !poolSaving && setPoolEditing(null)}
        title={poolEditing === "new" ? "新建协议池" : "编辑协议池"}
        description="勾选顺序就是回退顺序。接入时选择第一个当前可用且未超容量的节点。"
        footer={<><Button variant="outline" disabled={poolSaving} onClick={() => setPoolEditing(null)}>取消</Button><Button disabled={poolSaving || !poolForm.name.trim() || !poolForm.memberIds.length} onClick={() => void savePool()}>{poolSaving ? <Spinner /> : null}保存</Button></>}
      >
        <div className="drawer-form">
          <label className="field"><DrawerFieldLabel required>协议池名称</DrawerFieldLabel><Input maxLength={64} value={poolForm.name} onChange={(event) => setPoolForm((current) => ({ ...current, name: event.target.value }))} /></label>
          <div className="field"><DrawerFieldLabel required>成员与回退顺序</DrawerFieldLabel><div className="rounded-lg border p-3 space-y-2">{rows.map((row) => {
            const selectedIndex = poolForm.memberIds.indexOf(row.id);
            return <label className="flex items-center justify-between gap-3" key={row.id}><span className="flex items-center gap-2"><Checkbox checked={selectedIndex >= 0} onCheckedChange={(checked) => setPoolForm((current) => ({ ...current, memberIds: checked ? [...current.memberIds, row.id] : current.memberIds.filter((id) => id !== row.id) }))} /><span>{row.name}</span></span><small className="text-muted-foreground">{selectedIndex >= 0 ? `优先级 ${selectedIndex + 1}` : "未启用"}</small></label>;
          })}</div><small>若要调整优先级，可取消后按目标顺序重新勾选。</small></div>
          <label className="field"><DrawerFieldLabel>备注</DrawerFieldLabel><Textarea rows={4} maxLength={512} value={poolForm.remark} onChange={(event) => setPoolForm((current) => ({ ...current, remark: event.target.value }))} /></label>
        </div>
      </Drawer>
      <Drawer
        open={Boolean(interfaceSpec)}
        onClose={() => setInterfaceSpec(null)}
        title="模板接入接口规范"
        description="这是模板开发者应遵循的渠道级公共配对契约。模板不直接绑定或写死协议节点 ID。"
        footer={<><Button variant="outline" onClick={() => setInterfaceSpec(null)}>关闭</Button><Button onClick={() => { if (interfaceSpec) void navigator.clipboard.writeText(JSON.stringify(interfaceSpec, null, 2)).then(() => toast.success("接口规范已复制")); }}>复制 JSON</Button></>}
      >
        {interfaceSpec ? <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border bg-muted/40 p-4 text-xs leading-5">{JSON.stringify(interfaceSpec, null, 2)}</pre> : null}
      </Drawer>
    </StandardListPage>
  );
}
