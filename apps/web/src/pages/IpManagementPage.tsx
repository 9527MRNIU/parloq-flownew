import {
  BanIcon,
  CheckCircle2Icon,
  CircleGaugeIcon,
  LinkIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldCheckIcon,
  SlidersHorizontalIcon,
  Trash2Icon,
  UnlinkIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ListToolbar, StandardListPage } from "../components/list-page";
import {
  Badge,
  Button,
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
  Textarea,
  confirmAction,
  toast,
} from "../components/ui";

type ProxyStatus = "healthy" | "unhealthy" | "testing" | "disabled" | "unknown";
type IpProxy = {
  id: string | number;
  publicId: string;
  name: string;
  protocol: string;
  host: string;
  port: number;
  usernameMasked: string;
  passwordMasked: string;
  countryCode: string;
  countryName: string;
  provider: string;
  enabled: boolean;
  status: ProxyStatus;
  latencyMs?: number | null;
  lastCheckedAt?: string;
  lastError?: string;
  bindingCount: number;
  createdAt?: string;
};
type ProxyBinding = {
  id: string | number;
  publicId: string;
  proxyPublicId: string;
  accountPublicId: string;
  accountName?: string;
  accountPhone?: string;
  createdAt?: string;
};
type AccountOption = { id: string; label: string; status: string };
type AllocationMode =
  | "strict_one_to_one"
  | "tenant_reuse"
  | "least_load"
  | "manual";
type CountryMatch = "strict" | "prefer" | "off";
type AllocationPolicy = {
  allocationMode: AllocationMode;
  countryMatch: CountryMatch;
  maxAccountsPerIp: number;
  avoidUnhealthy: boolean;
  stickyBinding: boolean;
};
type BulkImportResult = {
  line: number;
  status: "created" | "duplicate" | "failed";
  reason?: string;
  proxyId?: string;
};
type BulkImportSummary = {
  total: number;
  created: number;
  duplicate: number;
  failed: number;
};

const defaultPolicy: AllocationPolicy = {
  allocationMode: "least_load",
  countryMatch: "prefer",
  maxAccountsPerIp: 5,
  avoidUnhealthy: true,
  stickyBinding: true,
};

const allocationDescriptions: Record<AllocationMode, string> = {
  strict_one_to_one:
    "严格 1:1：每个 IP 最多绑定一个账号，隔离最强，但需要准备更多代理资源。",
  tenant_reuse:
    "租户内复用：同一客户的账号可共用 IP，不会把该 IP 自动分给其他客户。",
  least_load:
    "低负载优先：从符合条件的代理中选择当前绑定数最少的 IP，兼顾利用率与稳定性。",
  manual:
    "手动分配：系统不自动选择 IP，账号必须由管理员显式绑定后才能使用代理。",
};
const countryDescriptions: Record<CountryMatch, string> = {
  strict: "严格匹配：找不到账号目标国家的健康 IP 时不自动分配。",
  prefer: "国家优先：优先使用同国家 IP，不足时再选择其他符合条件的 IP。",
  off: "关闭匹配：分配时不考虑账号与 IP 的国家信息。",
};

function normalizePolicy(input: unknown): AllocationPolicy {
  const row = (input || {}) as Record<string, unknown>;
  const allocationMode = text(row, "allocationMode", "allocation_mode");
  const countryMatch = text(row, "countryMatch", "country_match");
  return {
    allocationMode: [
      "strict_one_to_one",
      "tenant_reuse",
      "least_load",
      "manual",
    ].includes(allocationMode)
      ? (allocationMode as AllocationMode)
      : defaultPolicy.allocationMode,
    countryMatch: ["strict", "prefer", "off"].includes(countryMatch)
      ? (countryMatch as CountryMatch)
      : defaultPolicy.countryMatch,
    maxAccountsPerIp: Math.max(
      1,
      Number(
        row.maxAccountsPerIp ??
          row.max_accounts_per_ip ??
          defaultPolicy.maxAccountsPerIp,
      ),
    ),
    avoidUnhealthy: Boolean(
      row.avoidUnhealthy ??
        row.avoid_unhealthy ??
        defaultPolicy.avoidUnhealthy,
    ),
    stickyBinding: Boolean(
      row.stickyBinding ?? row.sticky_binding ?? defaultPolicy.stickyBinding,
    ),
  };
}

function text(row: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys)
    if (row[key] !== undefined && row[key] !== null) return String(row[key]);
  return "";
}

function maskCredential(value: string) {
  if (!value) return "-";
  if (value.includes("•") || value.includes("*")) return value;
  if (value.length <= 2) return "••••";
  return `${value.slice(0, 2)}${"•".repeat(Math.min(6, value.length - 2))}`;
}

function countryName(code: string) {
  if (!code) return "";
  try {
    return (
      new Intl.DisplayNames(["zh-CN"], { type: "region" }).of(
        code.toUpperCase(),
      ) || code.toUpperCase()
    );
  } catch {
    return code.toUpperCase();
  }
}

function normalizeProxy(input: unknown): IpProxy {
  const row = input as Record<string, unknown>;
  const enabled = Boolean(row.enabled ?? row.isActive ?? row.is_active ?? true);
  const rawStatus = text(
    row,
    "healthStatus",
    "health_status",
    "status",
  ).toLowerCase();
  const status: ProxyStatus = !enabled
    ? "disabled"
    : rawStatus === "healthy" ||
        rawStatus === "active" ||
        rawStatus === "online"
      ? "healthy"
      : rawStatus === "unhealthy" ||
          rawStatus === "failed" ||
          rawStatus === "error"
        ? "unhealthy"
        : rawStatus === "testing" || rawStatus === "checking"
          ? "testing"
          : "unknown";
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    publicId: text(row, "publicId", "public_id", "id"),
    name: text(row, "name", "label") || "未命名代理",
    protocol:
      text(row, "protocol", "proxyType", "proxy_type").toLowerCase() || "http",
    host: text(row, "host", "hostname"),
    port: Number(row.port || 0),
    usernameMasked: maskCredential(
      text(
        row,
        "usernameMasked",
        "username_masked",
        "maskedUsername",
        "masked_username",
        "username",
      ),
    ),
    passwordMasked:
      text(
        row,
        "passwordMasked",
        "password_masked",
        "maskedPassword",
        "masked_password",
      ) || (row.hasPassword || row.has_password ? "••••••••" : "-"),
    countryCode: text(row, "countryCode", "country_code").toUpperCase(),
    countryName:
      text(row, "countryName", "country_name", "country") ||
      countryName(text(row, "countryCode", "country_code")),
    provider: text(row, "provider"),
    enabled,
    status,
    latencyMs:
      row.latencyMs === undefined && row.latency_ms === undefined
        ? null
        : Number(row.latencyMs ?? row.latency_ms),
    lastCheckedAt: text(row, "lastCheckedAt", "last_checked_at"),
    lastError: text(row, "lastError", "last_error"),
    bindingCount: Number(
      row.bindingCount ??
        row.binding_count ??
        row.accountCount ??
        row.account_count ??
        row.assignedAccountCount ??
        row.assigned_account_count ??
        0,
    ),
    createdAt: text(row, "createdAt", "created_at"),
  };
}

function normalizeBinding(input: unknown): ProxyBinding {
  const row = input as Record<string, unknown>;
  return {
    id: (row.id || row.publicId || row.public_id) as string | number,
    publicId: text(row, "publicId", "public_id", "id"),
    proxyPublicId: text(row, "proxyPublicId", "proxy_public_id"),
    accountPublicId: text(row, "accountPublicId", "account_public_id"),
    accountName: text(row, "accountName", "account_name"),
    accountPhone: text(row, "accountPhone", "account_phone", "phone"),
    createdAt: text(row, "createdAt", "created_at"),
  };
}

function healthBadge(row: IpProxy) {
  if (!row.enabled || row.status === "disabled")
    return <Badge tone="neutral">已停用</Badge>;
  if (row.status === "healthy") return <Badge tone="success">健康</Badge>;
  if (row.status === "unhealthy") return <Badge tone="danger">异常</Badge>;
  if (row.status === "testing") return <Badge tone="warning">检测中</Badge>;
  return <Badge tone="warning">待检测</Badge>;
}

export function IpManagementPage() {
  const { can } = useAuth();
  const canManage = can("resources.ip.manage");
  const [rows, setRows] = useState<IpProxy[]>([]);
  const [bindings, setBindings] = useState<ProxyBinding[]>([]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [bindingsLoading, setBindingsLoading] = useState(false);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [protocol, setProtocol] = useState("all");
  const [country, setCountry] = useState("all");
  const [status, setStatus] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<IpProxy | null>(null);
  const [pending, setPending] = useState(false);
  const [bulkDrawerOpen, setBulkDrawerOpen] = useState(false);
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkResult, setBulkResult] = useState<{
    summary: BulkImportSummary;
    results: BulkImportResult[];
  } | null>(null);
  const [bulkDefaults, setBulkDefaults] = useState({
    protocol: "http",
    countryCode: "",
    provider: "",
    enabled: true,
  });
  const [testingIds, setTestingIds] = useState<string[]>([]);
  const [accountPublicId, setAccountPublicId] = useState("");
  const [bindingPending, setBindingPending] = useState(false);
  const [policy, setPolicy] = useState<AllocationPolicy>(defaultPolicy);
  const [policyDrawerOpen, setPolicyDrawerOpen] = useState(false);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyError, setPolicyError] = useState("");
  const [form, setForm] = useState({
    name: "",
    protocol: "http",
    host: "",
    port: "",
    username: "",
    password: "",
    countryCode: "",
    provider: "",
    enabled: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [payload, accountPayload] = await Promise.all([
        apiRequest("/api/ip-proxies?page=1&pageSize=100"),
        apiRequest("/api/personal-accounts?pageSize=100"),
      ]);
      const list = unwrapList<unknown>(payload);
      const nextRows = list.rows.map(normalizeProxy);
      setRows(nextRows);
      setAccounts(
        unwrapList<Record<string, unknown>>(accountPayload)
          .rows.map((row) => ({
            id: text(row, "publicId", "public_id", "id"),
            label: `${text(row, "name") || text(row, "phone") || text(row, "id")}${text(row, "phone") && text(row, "phone") !== text(row, "name") ? ` · ${text(row, "phone")}` : ""}`,
            status: text(row, "status"),
          }))
          .filter((row) => row.id),
      );
      setSelectedId((current) =>
        current && nextRows.some((row) => row.publicId === current)
          ? current
          : nextRows[0]?.publicId || "",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载 IP 代理失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPolicy = useCallback(async () => {
    setPolicyLoading(true);
    setPolicyError("");
    try {
      const payload = await apiRequest("/api/ip-allocation-policy");
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        payload) as Record<string, unknown>;
      setPolicy(normalizePolicy(data.policy || data));
    } catch (caught) {
      setPolicyError(
        caught instanceof Error ? caught.message : "IP 分配策略加载失败",
      );
    } finally {
      setPolicyLoading(false);
    }
  }, []);

  const loadBindings = useCallback(async (proxyPublicId: string) => {
    if (!proxyPublicId) {
      setBindings([]);
      return;
    }
    setBindingsLoading(true);
    try {
      const payload = await apiRequest(
        `/api/ip-proxy-bindings?proxyPublicId=${encodeURIComponent(proxyPublicId)}&pageSize=100`,
      );
      setBindings(
        unwrapList<unknown>(payload)
          .rows.map(normalizeBinding)
          .filter(
            (row) => !row.proxyPublicId || row.proxyPublicId === proxyPublicId,
          ),
      );
    } catch {
      setBindings([]);
    } finally {
      setBindingsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    void loadPolicy();
  }, [loadPolicy]);
  useEffect(() => {
    void loadBindings(selectedId);
  }, [loadBindings, selectedId]);

  const countries = useMemo(
    () =>
      Array.from(
        new Map(
          rows
            .filter((row) => row.countryCode || row.countryName)
            .map((row) => [
              row.countryCode || row.countryName,
              row.countryName || row.countryCode,
            ]),
        ).entries(),
      ).sort((a, b) => a[1].localeCompare(b[1], "zh-CN")),
    [rows],
  );
  const visibleRows = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return rows.filter((row) => {
      if (
        search &&
        !`${row.name} ${row.host} ${row.countryName} ${row.countryCode} ${row.provider}`
          .toLowerCase()
          .includes(search)
      )
        return false;
      if (protocol !== "all" && row.protocol !== protocol) return false;
      if (country !== "all" && (row.countryCode || row.countryName) !== country)
        return false;
      if (status !== "all" && row.status !== status) return false;
      return true;
    });
  }, [country, keyword, protocol, rows, status]);
  const selected = rows.find((row) => row.publicId === selectedId) || null;
  const bulkLineCount = useMemo(
    () =>
      bulkText
        .split(/\r?\n/)
        .filter((line) => line.trim() && !line.trim().startsWith("#")).length,
    [bulkText],
  );
  function openBulkCreate() {
    setBulkResult(null);
    setBulkText("");
    setBulkDrawerOpen(true);
  }
  function openEdit(row: IpProxy) {
    setEditing(row);
    setForm({
      name: row.name,
      protocol: row.protocol,
      host: row.host,
      port: String(row.port || ""),
      username: "",
      password: "",
      countryCode: row.countryCode,
      provider: row.provider,
      enabled: row.enabled,
    });
    setDialogOpen(true);
  }
  function updateForm(key: keyof typeof form, value: string | boolean) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    if (!editing || !form.name.trim() || !form.host.trim() || !form.port)
      return;
    setPending(true);
    try {
      const body = {
        name: form.name.trim(),
        protocol: form.protocol,
        host: form.host.trim(),
        port: Number(form.port),
        username: form.username || undefined,
        password: form.password || undefined,
        countryCode: form.countryCode.trim().toUpperCase() || undefined,
        provider: form.provider.trim() || undefined,
        enabled: form.enabled,
      };
      await apiRequest(`/api/ip-proxies/${editing.publicId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setDialogOpen(false);
      await load();
      toast.success("代理已更新");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存代理失败");
    } finally {
      setPending(false);
    }
  }

  async function bulkCreate() {
    if (!bulkLineCount || bulkLineCount > 1000) return;
    setBulkPending(true);
    setBulkResult(null);
    try {
      const payload = await apiRequest("/api/ip-proxies/bulk", {
        method: "POST",
        body: JSON.stringify({
          lines: bulkText.split(/\r?\n/),
          defaultProtocol: bulkDefaults.protocol,
          countryCode:
            bulkDefaults.countryCode.trim().toUpperCase() || undefined,
          provider: bulkDefaults.provider.trim() || undefined,
          enabled: bulkDefaults.enabled,
        }),
      });
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        payload) as Record<string, unknown>;
      const rawSummary = (data.summary || {}) as Record<string, unknown>;
      const summary: BulkImportSummary = {
        total: Number(rawSummary.total || 0),
        created: Number(rawSummary.created || 0),
        duplicate: Number(rawSummary.duplicate || 0),
        failed: Number(rawSummary.failed || 0),
      };
      const results = Array.isArray(data.results)
        ? (data.results as BulkImportResult[])
        : [];
      setBulkResult({ summary, results });
      await load();
      if (!summary.failed && !summary.duplicate) {
        toast.success(`已批量添加 ${summary.created} 条代理`);
        setBulkDrawerOpen(false);
        setBulkText("");
      } else {
        toast.warning(
          `导入完成：新增 ${summary.created}，重复 ${summary.duplicate}，失败 ${summary.failed}`,
        );
      }
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "批量添加代理失败");
    } finally {
      setBulkPending(false);
    }
  }

  async function toggle(row: IpProxy) {
    try {
      await apiRequest(`/api/ip-proxies/${row.publicId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "更新状态失败");
    }
  }
  async function healthTest(row: IpProxy) {
    setTestingIds((current) => [...current, row.publicId]);
    try {
      await apiRequest(`/api/ip-proxies/${row.publicId}/test`, {
        method: "POST",
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "健康检测失败");
    } finally {
      setTestingIds((current) => current.filter((id) => id !== row.publicId));
    }
  }
  async function archive(row: IpProxy) {
    if (
      !(await confirmAction({
        title: `归档代理“${row.name}”？`,
        description: "已有绑定时需先解绑账号，归档后不会再自动分配。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`/api/ip-proxies/${row.publicId}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档失败");
    }
  }
  async function bindAccount() {
    if (!selected || !accountPublicId.trim()) return;
    setBindingPending(true);
    try {
      await apiRequest(`/api/personal-accounts/${accountPublicId.trim()}`, {
        method: "PATCH",
        body: JSON.stringify({ proxyPublicId: selected.publicId }),
      });
      setAccountPublicId("");
      await Promise.all([loadBindings(selected.publicId), load()]);
    } catch (caught) {
      toast.error(
        caught instanceof Error
          ? caught.message
          : "绑定账号失败；在线账号请先断开连接",
      );
    } finally {
      setBindingPending(false);
    }
  }
  async function unbind(binding: ProxyBinding) {
    if (
      !(await confirmAction({
        title: `解绑账号 ${binding.accountName || binding.accountPublicId}？`,
        description: "在线账号需先断开连接后才能解绑代理。",
        confirmText: "确认解绑",
      }))
    )
      return;
    try {
      await apiRequest(`/api/personal-accounts/${binding.accountPublicId}`, {
        method: "PATCH",
        body: JSON.stringify({ proxyPublicId: null }),
      });
      await Promise.all([loadBindings(selectedId), load()]);
    } catch (caught) {
      toast.error(
        caught instanceof Error
          ? caught.message
          : "解绑失败；在线账号请先断开连接",
      );
    }
  }

  async function savePolicy() {
    setPolicySaving(true);
    setPolicyError("");
    try {
      const payload = await apiRequest("/api/ip-allocation-policy", {
        method: "PATCH",
        body: JSON.stringify(policy),
      });
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        payload) as Record<string, unknown>;
      setPolicy(normalizePolicy(data.policy || data));
      toast.success("IP 分配策略已保存");
      setPolicyDrawerOpen(false);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "IP 分配策略保存失败";
      setPolicyError(message);
      toast.error(message);
    } finally {
      setPolicySaving(false);
    }
  }

  return (
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索名称、主机、国家或地区",
        }}
        filters={
          <>
            <SelectField
              ariaLabel="协议筛选"
              value={protocol}
              onValueChange={setProtocol}
              options={[
                { value: "all", label: "全部协议" },
                { value: "http", label: "HTTP" },
                { value: "https", label: "HTTPS" },
                { value: "socks5", label: "SOCKS5" },
              ]}
            />
            <SelectField
              ariaLabel="国家筛选"
              value={country}
              onValueChange={setCountry}
              options={[
                { value: "all", label: "全部国家" },
                ...countries.map(([value, label]) => ({ value, label })),
              ]}
            />
            <SelectField
              ariaLabel="状态筛选"
              value={status}
              onValueChange={setStatus}
              options={[
                { value: "all", label: "全部状态" },
                { value: "healthy", label: "健康" },
                { value: "unhealthy", label: "异常" },
                { value: "unknown", label: "待检测" },
                { value: "disabled", label: "已停用" },
              ]}
            />
          </>
        }
        meta={`${visibleRows.length} 条代理`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setPolicyDrawerOpen(true);
                void loadPolicy();
              }}
            >
              <SlidersHorizontalIcon size={16} />
              {policyError ? "分配策略（异常）" : "分配策略"}
            </Button>
            <Button
              variant="outline"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCwIcon size={16} className={loading ? "spin" : ""} />
              刷新
            </Button>
            {canManage ? (
              <Button onClick={openBulkCreate}>
                <PlusIcon size={17} />
                批量添加
              </Button>
            ) : null}
          </>
        }
      />

      <div className="ip-content-grid">
        <section className="card table-card">
          {loading ? (
            <div className="loading-state">
              <Spinner />
              正在加载 IP 代理…
            </div>
          ) : error ? (
            <div className="error-state">
              <strong>加载失败</strong>
              <span>{error}</span>
              <Button variant="outline" onClick={() => void load()}>
                重试
              </Button>
            </div>
          ) : visibleRows.length ? (
            <div className="table-scroll">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代理</TableHead>
                    <TableHead>国家 / 地区</TableHead>
                    <TableHead>凭证</TableHead>
                    <TableHead>健康</TableHead>
                    <TableHead>绑定</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleRows.map((row) => (
                    <TableRow
                      key={row.publicId}
                      className={
                        selectedId === row.publicId ? "selected-row" : ""
                      }
                      onClick={() => setSelectedId(row.publicId)}
                    >
                      <TableCell>
                        <div className="cell-main">
                          <strong>{row.name}</strong>
                          <span>
                            {row.protocol.toUpperCase()} · {row.host}:{row.port}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="cell-main country-cell">
                          <strong>
                            {row.countryName || row.countryCode || "未设置"}
                          </strong>
                          <span>
                            {[row.countryCode, row.provider]
                              .filter(Boolean)
                              .join(" · ") || "-"}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="credential-cell">
                          <span>用户 {row.usernameMasked}</span>
                          <span>密码 {row.passwordMasked}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="health-cell">
                          <span>
                            {row.latencyMs ? `${row.latencyMs} ms` : "-"}
                          </span>
                          <small title={row.lastError}>
                            {row.lastError || formatDateTime(row.lastCheckedAt)}
                          </small>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {row.bindingCount}
                      </TableCell>
                      <TableCell>{healthBadge(row)}</TableCell>
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        {canManage ? <div className="flex items-center justify-end gap-1">
                          <IconButton
                            label="健康检测"
                            disabled={
                              !row.enabled || testingIds.includes(row.publicId)
                            }
                            onClick={() => void healthTest(row)}
                          >
                            {testingIds.includes(row.publicId) ? (
                              <LoaderCircleIcon className="spin" size={16} />
                            ) : (
                              <PlayIcon size={16} />
                            )}
                          </IconButton>
                          <IconButton
                            label="编辑"
                            onClick={() => openEdit(row)}
                          >
                            <PencilIcon size={16} />
                          </IconButton>
                          <IconButton
                            label={row.enabled ? "停用" : "启用"}
                            onClick={() => void toggle(row)}
                          >
                            {row.enabled ? (
                              <BanIcon size={16} />
                            ) : (
                              <CheckCircle2Icon size={16} />
                            )}
                          </IconButton>
                          <IconButton
                            variant="destructive"
                            label="归档"
                            onClick={() => void archive(row)}
                          >
                            <Trash2Icon size={16} />
                          </IconButton>
                        </div> : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState
              title="没有匹配的代理"
              description="调整筛选条件，或添加新的 HTTP、HTTPS、SOCKS5 代理。"
            />
          )}
        </section>

        <aside className="card binding-panel">
          <header>
            <div>
              <h2>账号绑定</h2>
              <p>{selected ? selected.name : "请先选择代理"}</p>
            </div>
            <CircleGaugeIcon size={19} />
          </header>
          {selected ? (
            <>
              <div className="binding-notice">
                通过统一账号池建立固定绑定，并同步到发送网关。在线账号更换代理前需要先断开连接。
              </div>
              {canManage ? <form
                className="binding-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void bindAccount();
                }}
              >
                <label className="field">
                  <span>账号</span>
                  <SelectField
                    ariaLabel="账号"
                    value={accountPublicId}
                    placeholder="请选择账号"
                    onValueChange={setAccountPublicId}
                    options={accounts.map((account) => ({
                      value: account.id,
                      label: `${account.label} · ${account.status || "未知状态"}`,
                    }))}
                  />
                </label>
                <Button
                  type="submit"
                  disabled={bindingPending || !accountPublicId.trim()}
                >
                  {bindingPending ? <Spinner /> : <LinkIcon size={16} />}绑定
                </Button>
              </form> : null}
              <div className="binding-list-header">
                <strong>已绑定账号</strong>
                <span>{bindings.length}</span>
              </div>
              {bindingsLoading ? (
                <div className="binding-loading">
                  <Spinner />
                </div>
              ) : bindings.length ? (
                <div className="binding-list">
                  {bindings.map((binding) => (
                    <div
                      className="binding-item"
                      key={binding.publicId || binding.id}
                    >
                      <span className="small-avatar">
                        <ShieldCheckIcon size={15} />
                      </span>
                      <div>
                        <strong>
                          {binding.accountName ||
                            binding.accountPhone ||
                            binding.accountPublicId}
                        </strong>
                        <small>{binding.accountPublicId}</small>
                      </div>
                      {canManage ? (
                        <IconButton
                          label="解绑"
                          onClick={() => void unbind(binding)}
                        >
                          <UnlinkIcon size={15} />
                        </IconButton>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="暂无绑定"
                  description="从统一账号池选择账号，将它固定到当前代理。"
                />
              )}
            </>
          ) : (
            <EmptyState
              title="选择一个代理"
              description="选择左侧代理后，可以查看和维护账号绑定关系。"
            />
          )}
        </aside>
      </div>

      <Drawer
        open={policyDrawerOpen}
        onClose={() => !policySaving && setPolicyDrawerOpen(false)}
        title="账号 IP 分配策略"
        description="设置账号首次分配代理时的隔离程度、国家匹配、容量限制和健康保护。"
        wide
        footer={
          <>
            <Button
              variant="outline"
              disabled={policySaving}
              onClick={() => setPolicyDrawerOpen(false)}
            >
              取消
            </Button>
            {canManage ? (
              <Button
                disabled={
                  policyLoading || policySaving || Boolean(policyError)
                }
                onClick={() => void savePolicy()}
              >
                {policySaving ? <Spinner /> : <SaveIcon size={16} />}
                保存策略
              </Button>
            ) : null}
          </>
        }
      >
        {policyLoading ? (
          <div className="loading-state min-h-44">
            <Spinner />
            正在加载分配策略…
          </div>
        ) : (
          <div className="drawer-form">
            {policyError ? (
              <div className="flex flex-col items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive md:flex-row md:items-center md:justify-between">
                <span>{policyError}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void loadPolicy()}
                >
                  重新读取
                </Button>
              </div>
            ) : null}
            <div className="form-grid">
              <label className="field">
                <span>分配模式</span>
                <SelectField
                  ariaLabel="IP 分配模式"
                  className="w-full"
                  value={policy.allocationMode}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onValueChange={(value) =>
                    setPolicy((current) => ({
                      ...current,
                      allocationMode: value as AllocationMode,
                      maxAccountsPerIp:
                        value === "strict_one_to_one"
                          ? 1
                          : current.maxAccountsPerIp,
                    }))
                  }
                  options={[
                    { value: "strict_one_to_one", label: "严格 1:1" },
                    { value: "tenant_reuse", label: "租户内复用" },
                    { value: "least_load", label: "低负载优先（推荐）" },
                    { value: "manual", label: "仅手动分配" },
                  ]}
                />
                <small>{allocationDescriptions[policy.allocationMode]}</small>
              </label>
              <label className="field">
                <span>国家匹配</span>
                <SelectField
                  ariaLabel="国家匹配策略"
                  className="w-full"
                  value={policy.countryMatch}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onValueChange={(value) =>
                    setPolicy((current) => ({
                      ...current,
                      countryMatch: value as CountryMatch,
                    }))
                  }
                  options={[
                    { value: "strict", label: "严格匹配" },
                    { value: "prefer", label: "国家优先（推荐）" },
                    { value: "off", label: "关闭匹配" },
                  ]}
                />
                <small>{countryDescriptions[policy.countryMatch]}</small>
              </label>
              <label className="field form-span-2">
                <span>每个 IP 最多账号数</span>
                <Input
                  type="number"
                  min="1"
                  max="10000"
                  value={policy.maxAccountsPerIp}
                  disabled={
                    !canManage ||
                    policySaving ||
                    Boolean(policyError) ||
                    policy.allocationMode === "strict_one_to_one"
                  }
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      maxAccountsPerIp: Math.max(
                        1,
                        Math.min(10000, Number(event.target.value) || 1),
                      ),
                    }))
                  }
                />
                <small>
                  {policy.allocationMode === "strict_one_to_one"
                    ? "严格 1:1 模式固定按 1 个账号执行。"
                    : "达到上限的 IP 不再参与自动分配。"}
                </small>
              </label>
            </div>
            <div className="grid gap-3">
              <label className="switch-row">
                <span>
                  <strong>避开异常 IP</strong>
                  <small>自动分配时排除健康检测异常或已停用的代理。</small>
                </span>
                <Switch
                  checked={policy.avoidUnhealthy}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onCheckedChange={(checked) =>
                    setPolicy((current) => ({
                      ...current,
                      avoidUnhealthy: checked,
                    }))
                  }
                  aria-label="避开异常 IP"
                />
              </label>
              <label className="switch-row">
                <span>
                  <strong>保持固定绑定</strong>
                  <small>账号成功分配后持续使用同一 IP，除非管理员手动解绑。</small>
                </span>
                <Switch
                  checked={policy.stickyBinding}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onCheckedChange={(checked) =>
                    setPolicy((current) => ({
                      ...current,
                      stickyBinding: checked,
                    }))
                  }
                  aria-label="保持固定绑定"
                />
              </label>
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={bulkDrawerOpen}
        onClose={() => !bulkPending && setBulkDrawerOpen(false)}
        title="批量添加 IP 代理"
        description="每行一个代理，整批共用下方默认设置；代理凭证会加密保存。"
        wide
        footer={
          <>
            <Button
              variant="outline"
              disabled={bulkPending}
              onClick={() => setBulkDrawerOpen(false)}
            >
              取消
            </Button>
            <Button
              disabled={
                bulkPending || !bulkLineCount || bulkLineCount > 1000
              }
              onClick={() => void bulkCreate()}
            >
              {bulkPending ? (
                <LoaderCircleIcon className="spin" size={17} />
              ) : (
                <PlusIcon size={17} />
              )}
              开始导入
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <span>代理列表</span>
            <Textarea
              className="min-h-64 resize-y font-mono"
              value={bulkText}
              onChange={(event) => {
                setBulkText(event.target.value);
                setBulkResult(null);
              }}
              placeholder={[
                "203.0.113.10:8080",
                "203.0.113.11:8080:username:password",
                "username:password@203.0.113.12:1080",
                "socks5://username:password@203.0.113.13:1080",
              ].join("\n")}
              spellCheck={false}
            />
            <small>
              已填写 {bulkLineCount} / 1000 条。支持 host:port、
              host:port:用户名:密码、用户名:密码@host:port 和带协议 URL；空行或
              # 开头的注释会忽略。
            </small>
          </label>

          <div className="grid gap-3 sm:grid-cols-3">
            <label className="field">
              <span>默认协议</span>
              <SelectField
                value={bulkDefaults.protocol}
                onValueChange={(value) =>
                  setBulkDefaults((current) => ({
                    ...current,
                    protocol: value,
                  }))
                }
                options={[
                  { value: "http", label: "HTTP" },
                  { value: "https", label: "HTTPS" },
                  { value: "socks5", label: "SOCKS5" },
                ]}
              />
            </label>
            <label className="field">
              <span>国家代码（可选）</span>
              <Input
                value={bulkDefaults.countryCode}
                maxLength={2}
                onChange={(event) =>
                  setBulkDefaults((current) => ({
                    ...current,
                    countryCode: event.target.value,
                  }))
                }
                placeholder="US"
              />
            </label>
            <label className="field">
              <span>代理供应商（可选）</span>
              <Input
                value={bulkDefaults.provider}
                maxLength={120}
                onChange={(event) =>
                  setBulkDefaults((current) => ({
                    ...current,
                    provider: event.target.value,
                  }))
                }
                placeholder="例如：IPRoyal"
              />
            </label>
          </div>

          <label className="switch-row">
            <span>
              <strong>导入后启用</strong>
              <small>关闭时代理仍会入库，但不会参与自动分配。</small>
            </span>
            <Switch
              checked={bulkDefaults.enabled}
              onCheckedChange={(checked) =>
                setBulkDefaults((current) => ({
                  ...current,
                  enabled: checked,
                }))
              }
              aria-label="导入后启用"
            />
          </label>

          {bulkLineCount > 1000 ? (
            <div className="form-error" role="alert">
              一次最多导入 1000 条，请拆分后再提交。
            </div>
          ) : null}

          {bulkResult ? (
            <div className="rounded-lg border bg-muted/30 p-4">
              <strong>导入结果</strong>
              <p className="mt-1 text-sm text-muted-foreground">
                共 {bulkResult.summary.total} 条 · 新增 {bulkResult.summary.created}
                条 · 重复 {bulkResult.summary.duplicate} 条 · 失败 {bulkResult.summary.failed}
                条
              </p>
              {bulkResult.results.some(
                (item) => item.status !== "created",
              ) ? (
                <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
                  {bulkResult.results
                    .filter((item) => item.status !== "created")
                    .map((item) => (
                      <div
                        className="flex items-start gap-2 rounded-md border bg-background px-3 py-2 text-sm"
                        key={`${item.line}-${item.status}`}
                      >
                        <Badge
                          tone={
                            item.status === "failed" ? "danger" : "warning"
                          }
                        >
                          {item.status === "failed" ? "失败" : "重复"}
                        </Badge>
                        <span>
                          第 {item.line} 行
                          {item.reason ? `：${item.reason}` : ""}
                        </span>
                      </div>
                    ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </Drawer>

      <Drawer
        open={dialogOpen}
        onClose={() => !pending && setDialogOpen(false)}
        title="编辑 IP 代理"
        description="代理凭证只会加密保存；页面和接口不返回原始密码。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => setDialogOpen(false)}
            >
              取消
            </Button>
            <Button
              disabled={
                pending || !form.name.trim() || !form.host.trim() || !form.port
              }
              onClick={() => void save()}
            >
              {pending ? <LoaderCircleIcon className="spin" size={17} /> : null}
              保存代理
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <div className="form-grid">
            <label className="field form-span-2">
              <span>代理名称</span>
              <Input
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
                placeholder="例如：美国线路 A01"
              />
            </label>
            <label className="field">
              <span>协议</span>
              <SelectField
                value={form.protocol}
                onValueChange={(value) => updateForm("protocol", value)}
                options={[
                  { value: "http", label: "HTTP" },
                  { value: "https", label: "HTTPS" },
                  { value: "socks5", label: "SOCKS5" },
                ]}
              />
            </label>
            <label className="field">
              <span>端口</span>
              <Input
                type="number"
                min="1"
                max="65535"
                value={form.port}
                onChange={(event) => updateForm("port", event.target.value)}
                placeholder="8080"
              />
            </label>
            <label className="field form-span-2">
              <span>主机地址</span>
              <Input
                value={form.host}
                onChange={(event) => updateForm("host", event.target.value)}
                placeholder="proxy.example.com 或 203.0.113.10"
              />
            </label>
            <label className="field">
              <span>用户名（留空不修改）</span>
              <Input
                value={form.username}
                onChange={(event) => updateForm("username", event.target.value)}
                autoComplete="off"
                placeholder={editing?.usernameMasked || "未设置"}
              />
            </label>
            <label className="field">
              <span>密码（留空不修改）</span>
              <Input
                type="password"
                value={form.password}
                onChange={(event) => updateForm("password", event.target.value)}
                autoComplete="new-password"
                placeholder={editing?.passwordMasked || "未设置"}
              />
            </label>
            <label className="field">
              <span>国家代码</span>
              <Input
                value={form.countryCode}
                maxLength={2}
                onChange={(event) =>
                  updateForm("countryCode", event.target.value)
                }
                placeholder="US"
              />
            </label>
            <label className="field">
              <span>代理供应商（可选）</span>
              <Input
                value={form.provider}
                onChange={(event) => updateForm("provider", event.target.value)}
                placeholder="例如：IPRoyal"
              />
            </label>
          </div>
          <label className="switch-row">
            <span>
              <strong>启用代理</strong>
              <small>停用后不会分配给账号，也不能发起健康检测。</small>
            </span>
            <Switch
              checked={form.enabled}
              onCheckedChange={(checked) => updateForm("enabled", checked)}
              aria-label="启用代理"
            />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
