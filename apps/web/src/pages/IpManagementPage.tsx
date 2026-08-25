import {
  ArrowRightLeftIcon,
  ChevronDownIcon,
  CircleGaugeIcon,
  EyeIcon,
  ListChecksIcon,
  LoaderCircleIcon,
  PlusIcon,
  PowerIcon,
  PowerOffIcon,
  RefreshCwIcon,
  SaveIcon,
  SlidersHorizontalIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiNdjsonRequest,
  apiRequest,
  formatDateTime,
  unwrapList,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ListPagination,
  ListSortableHead,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  type ListSortOrder,
} from "../components/list-page";
import {
  DrawerChoiceGroup,
  DrawerFieldLabel,
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";
import {
  EntityPrimaryCell,
  type EntityStatusMeta,
} from "../components/entity-primary-cell";
import {
  CountryDisplay,
  CountryFlag,
  countryDisplayName,
} from "../components/country-display";
import {
  Badge,
  Button,
  Checkbox,
  Drawer,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  Input,
  SearchableSelect,
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
import {
  entityRowKey,
  snowflakeId,
} from "../lib/entity-identifiers";
import { countryOptions } from "../lib/countries";
import { formatPhoneDisplay } from "../lib/utils";

type ProxyStatus = "healthy" | "unhealthy" | "testing" | "disabled" | "unknown";
type ProxySortBy =
  | "id"
  | "protocol"
  | "countryCode"
  | "provider"
  | "healthStatus"
  | "createdAt"
  | "updatedAt";
type IpProxy = {
  id: string;
  readKey: string;
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
  consecutiveFailures: number;
  cooldownUntil?: string;
  lastCheckSource?: string;
  bindingCount: number;
  createdAt?: string;
  updatedAt?: string;
};
type AllocationMode =
  | "strict_one_to_one"
  | "tenant_reuse"
  | "least_load"
  | "manual";
type CountryMatch = "visitor_country" | "phone_country";
type AllocationPolicy = {
  allocationMode: AllocationMode;
  countryMatch: CountryMatch;
  maxAccountsPerIp: number;
  avoidUnhealthy: boolean;
  stickyBinding: boolean;
  failureThreshold: number;
  cooldownSeconds: number;
};
type BulkPreviewResult = {
  line: number;
  status: "checking" | "checked" | "duplicate" | "failed";
  reason?: string;
  protocol?: string;
  host?: string;
  port?: number;
  healthStatus?: "healthy" | "unhealthy";
  countryCode?: string;
  latencyMs?: number | null;
  error?: string;
};
type BulkPreviewSummary = {
  total: number;
  candidates: number;
  healthy: number;
  unhealthy: number;
  duplicate: number;
  failed: number;
};
type BulkPreviewData = {
  previewToken: string;
  summary: BulkPreviewSummary;
  results: BulkPreviewResult[];
};
type BulkPreviewStreamEvent =
  | { type: "snapshot"; results: BulkPreviewResult[] }
  | { type: "result"; result: BulkPreviewResult }
  | { type: "complete"; data: BulkPreviewData }
  | { type: "error"; status: number; detail: string };
type BulkDetectionResult = {
  line: number;
  key: string;
  endpoint: string;
  countryCode: string;
  countryName: string;
  status: "checking" | "healthy" | "unhealthy" | "duplicate" | "failed";
  latencyMs?: number | null;
  error?: string;
};
type RebindMode = "manual" | "automatic";
type BatchRebindResult = {
  bindingId: string;
  accountId: string;
  accountName: string;
  accountPhone: string;
  sourceProxyId: string;
  targetProxyId: string;
  status: "success" | "failed";
  error: string;
};
type BatchRebindSummary = {
  sourceProxies: number;
  accounts: number;
  migrated: number;
  failed: number;
  emptySources: number;
};

function upsertBulkPreviewResult(
  current: BulkPreviewResult[],
  next: BulkPreviewResult,
): BulkPreviewResult[] {
  const index = current.findIndex((item) => item.line === next.line);
  if (index < 0) {
    return [...current, next].sort((left, right) => left.line - right.line);
  }
  const updated = [...current];
  updated[index] = next;
  return updated;
}

const defaultPolicy: AllocationPolicy = {
  allocationMode: "least_load",
  countryMatch: "visitor_country",
  maxAccountsPerIp: 5,
  avoidUnhealthy: true,
  stickyBinding: true,
  failureThreshold: 2,
  cooldownSeconds: 900,
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
const allocationModeLabels: Record<AllocationMode, string> = {
  strict_one_to_one: "严格 1:1",
  tenant_reuse: "租户内复用",
  least_load: "低负载优先",
  manual: "仅手动分配",
};
const countryDescriptions: Record<CountryMatch, string> = {
  visitor_country:
    "访问国家：公开落地页按访客访问国家优先匹配；后台创建没有访问国家时回退到号码国家。",
  phone_country: "号码国家：按账号 E.164 号码识别的国家优先匹配代理。",
};

const proxyCountryOptions = countryOptions.map((option) => ({
  ...option,
  leading: <CountryFlag code={option.value} />,
}));

const optionalProxyCountryOptions = [
  {
    value: "",
    label: "自动检测",
    description: "首次健康检测时识别代理出口国家",
    keywords: "自动检测 auto detect 自动识别",
    leading: <CountryFlag code="WW" />,
  },
  ...proxyCountryOptions,
];

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
    countryMatch: ["visitor_country", "phone_country"].includes(countryMatch)
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
    failureThreshold: Math.max(
      1,
      Math.min(
        10,
        Number(
          row.failureThreshold ??
            row.failure_threshold ??
            defaultPolicy.failureThreshold,
        ),
      ),
    ),
    cooldownSeconds: Math.max(
      60,
      Math.min(
        86400,
        Number(
          row.cooldownSeconds ??
            row.cooldown_seconds ??
            defaultPolicy.cooldownSeconds,
        ),
      ),
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

function normalizeProxy(input: unknown): IpProxy {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  const countryCode = text(row, "countryCode", "country_code").toUpperCase();
  const latencyValue = row.latencyMs ?? row.latency_ms;
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
    id,
    readKey: entityRowKey(row, id, "ip-proxy", `${text(row, "host", "hostname")}:${String(row.port || "")}`),
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
    countryCode,
    countryName:
      text(row, "countryName", "country_name", "country") ||
      (countryCode ? countryDisplayName(countryCode) : ""),
    provider: text(row, "provider"),
    enabled,
    status,
    latencyMs: latencyValue === undefined || latencyValue === null
      ? null
      : Number(latencyValue),
    lastCheckedAt: text(row, "lastCheckedAt", "last_checked_at"),
    lastError: text(row, "lastError", "last_error"),
    consecutiveFailures: Number(
      row.consecutiveFailures ?? row.consecutive_failures ?? 0,
    ),
    cooldownUntil: text(row, "cooldownUntil", "cooldown_until"),
    lastCheckSource: text(row, "lastCheckSource", "last_check_source"),
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
    updatedAt: text(row, "updatedAt", "updated_at"),
  };
}

function bulkProxyEndpoint(rawLine: string, line: number): string {
  const withoutScheme = rawLine
    .trim()
    .replace(/^[a-z][a-z\d+.-]*:\/\//i, "");
  const authority = withoutScheme.includes("@")
    ? withoutScheme.slice(withoutScheme.lastIndexOf("@") + 1)
    : withoutScheme;
  const ipv6 = authority.match(/^(\[[^\]]+\]):(\d+)/);
  if (ipv6) return `${ipv6[1]}:${ipv6[2]}`;
  const endpoint = authority.match(/^([^:\s/]+):(\d+)/);
  return endpoint ? `${endpoint[1]}:${endpoint[2]}` : `第 ${line} 行（等待解析）`;
}

function proxyStatus(row: IpProxy): EntityStatusMeta {
  if (!row.enabled || row.status === "disabled")
    return { label: "已停用", description: "代理已停用，不会参与自动分配。", tone: "neutral" };
  if (row.status === "healthy")
    return { label: "健康", description: "最近一次健康检测通过，可以参与账号分配。", tone: "success" };
  if (row.status === "unhealthy")
    return {
      label: row.cooldownUntil ? "冷却中" : "异常",
      description:
        row.lastError ||
        (row.cooldownUntil
          ? `冷却至 ${formatDateTime(row.cooldownUntil)}`
          : "代理需要修复或手动复检。"),
      tone: "danger",
    };
  if (row.status === "testing")
    return { label: "检测中", description: "系统正在检测代理连通性与延迟。", tone: "warning" };
  return { label: "待检测", description: "代理尚未完成首次健康检测。", tone: "warning" };
}

function proxyAvailableForRebind(row: IpProxy): boolean {
  if (!row.enabled) return false;
  if (row.status !== "unhealthy") return true;
  if (!row.cooldownUntil) return false;
  const cooldownEndsAt = new Date(row.cooldownUntil).getTime();
  return Number.isFinite(cooldownEndsAt) && cooldownEndsAt <= Date.now();
}

export function IpManagementPage() {
  const { can } = useAuth();
  const canManage = can("resources.ip.manage");
  const [rows, setRows] = useState<IpProxy[]>([]);
  const [proxyOptions, setProxyOptions] = useState<IpProxy[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [protocol, setProtocol] = useState("all");
  const [country, setCountry] = useState("all");
  const [provider, setProvider] = useState("all");
  const [status, setStatus] = useState("all");
  const [sortBy, setSortBy] = useState<ProxySortBy>("id");
  const [sortOrder, setSortOrder] = useState<ListSortOrder>("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [filterCountries, setFilterCountries] = useState<string[]>([]);
  const [filterProviders, setFilterProviders] = useState<string[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<IpProxy | null>(null);
  const [pending, setPending] = useState(false);
  const [bulkDrawerOpen, setBulkDrawerOpen] = useState(false);
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkResult, setBulkResult] = useState<{
    summary: BulkPreviewSummary;
    results: BulkPreviewResult[];
  } | null>(null);
  const [bulkProgressResults, setBulkProgressResults] = useState<
    BulkPreviewResult[]
  >([]);
  const [bulkPreviewToken, setBulkPreviewToken] = useState("");
  const [bulkStage, setBulkStage] = useState<"importing" | "checking" | "">(
    "",
  );
  const [bulkConfirmMode, setBulkConfirmMode] = useState<
    "healthy" | "all" | ""
  >("");
  const bulkPreviewRequestRef = useRef<{
    requestId: string;
    controller: AbortController;
  } | null>(null);
  const [bulkDefaults, setBulkDefaults] = useState({
    protocol: "http",
    countryCode: "",
    provider: "",
    enabled: true,
  });
  const [selectedProxyIds, setSelectedProxyIds] = useState<string[]>([]);
  const [batchAction, setBatchAction] = useState<
    "test" | "enable" | "disable" | "rebind" | "delete" | ""
  >("");
  const [rebindDrawerOpen, setRebindDrawerOpen] = useState(false);
  const [rebindSourceIds, setRebindSourceIds] = useState<string[]>([]);
  const [rebindMode, setRebindMode] = useState<RebindMode>("automatic");
  const [rebindMappings, setRebindMappings] = useState<
    Record<string, string>
  >({});
  const [rebindResult, setRebindResult] = useState<{
    summary: BatchRebindSummary;
    results: BatchRebindResult[];
  } | null>(null);
  const [testingIds, setTestingIds] = useState<string[]>([]);
  const [policy, setPolicy] = useState<AllocationPolicy>(defaultPolicy);
  const [policyDrawerOpen, setPolicyDrawerOpen] = useState(false);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyError, setPolicyError] = useState("");
  const [form, setForm] = useState({
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
      const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      if (debouncedKeyword) query.set("keyword", debouncedKeyword);
      if (protocol !== "all") query.set("protocol", protocol);
      if (country !== "all") query.set("countryCode", country);
      if (provider !== "all") query.set("provider", provider);
      if (status !== "all") query.set("healthStatus", status);
      query.set("sortBy", sortBy);
      query.set("sortOrder", sortOrder);
      const [payload, optionPayload, filterPayload] = await Promise.all([
        apiRequest(`/api/ip-proxies?${query}`),
        apiRequest("/api/ip-proxies/options"),
        apiRequest("/api/ip-proxies/filter-options"),
      ]);
      const list = unwrapList<unknown>(payload);
      const nextRows = list.rows.map(normalizeProxy);
      setRows(nextRows);
      setTotal(list.total);
      setProxyOptions(unwrapList<unknown>(optionPayload).rows.map(normalizeProxy));
      const filterData = ((filterPayload as {
        data?: { countries?: unknown[]; providers?: unknown[] };
      }).data || {});
      setFilterCountries(Array.isArray(filterData.countries) ? filterData.countries.map(String) : []);
      setFilterProviders(
        Array.isArray(filterData.providers)
          ? filterData.providers.map(String)
          : [],
      );
      setSelectedId((current) =>
        current && nextRows.some((row) => row.id === current)
          ? current
          : "",
      );
    } catch (caught) {
      setRows([]);
      setTotal(0);
      setError(caught instanceof Error ? caught.message : "加载 IP 代理失败");
    } finally {
      setLoading(false);
    }
  }, [country, debouncedKeyword, page, pageSize, protocol, provider, sortBy, sortOrder, status]);

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

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    void loadPolicy();
  }, [loadPolicy]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
      setSelectedProxyIds([]);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);
  useEffect(() => { setPage(1); setSelectedProxyIds([]); }, [country, protocol, provider, status]);
  const rebindSourceRows = useMemo(() => {
    const sourceIdSet = new Set(rebindSourceIds);
    return proxyOptions.filter((row) => row.id && sourceIdSet.has(row.id));
  }, [proxyOptions, rebindSourceIds]);
  const rebindAccountCount = rebindSourceRows.reduce(
    (total, row) => total + row.bindingCount,
    0,
  );
  const automaticRebindTargets = useMemo(() => {
    const sourceIdSet = new Set(rebindSourceIds);
    return proxyOptions.filter(
      (row) =>
        row.id &&
        !sourceIdSet.has(row.id) &&
        proxyAvailableForRebind(row),
    );
  }, [proxyOptions, rebindSourceIds]);
  const manualRebindReady = rebindSourceRows
    .filter((row) => row.bindingCount > 0)
    .every((row) => Boolean(rebindMappings[row.id]));
  const pageProxyIds = useMemo(
    () => rows.map((row) => row.id).filter(Boolean),
    [rows],
  );
  const allPageSelected =
    Boolean(pageProxyIds.length) &&
    pageProxyIds.every((id) => selectedProxyIds.includes(id));
  const somePageSelected =
    !allPageSelected &&
    pageProxyIds.some((id) => selectedProxyIds.includes(id));
  const selected = rows.find((row) => row.id === selectedId) || null;
  function changeSort(nextSortBy: ProxySortBy, nextSortOrder: ListSortOrder) {
    setSortBy(nextSortBy);
    setSortOrder(nextSortOrder);
    setPage(1);
    setSelectedProxyIds([]);
  }
  const bulkLineCount = useMemo(
    () =>
      bulkText
        .split(/\r?\n/)
        .filter((line) => line.trim() && !line.trim().startsWith("#")).length,
    [bulkText],
  );
  const bulkDetectionResults = useMemo<BulkDetectionResult[]>(() => {
    const sourceResults = bulkResult?.results || bulkProgressResults;
    const detected: BulkDetectionResult[] = [];
    for (const item of sourceResults) {
      const countryCode = item.countryCode?.toUpperCase() || "";
      const detectionStatus =
        item.status === "checking"
          ? "checking"
          : item.status === "duplicate"
          ? "duplicate"
          : item.status === "failed"
          ? "failed"
          : item.healthStatus === "healthy"
          ? "healthy"
          : "unhealthy";
      detected.push({
        line: item.line,
        key: `preview-${item.line}`,
        endpoint:
          item.host && item.port
            ? `${item.host}:${item.port}`
            : `第 ${item.line} 行`,
        countryCode,
        countryName: countryCode ? countryDisplayName(countryCode) : "",
        status: detectionStatus,
        latencyMs: item.latencyMs,
        error: item.error || item.reason,
      });
    }
    return detected;
  }, [bulkProgressResults, bulkResult]);
  const bulkPendingDetectionResults = useMemo<BulkDetectionResult[]>(() => {
    if (!bulkPending || bulkStage !== "checking" || bulkResult) return [];
    const pendingRows: BulkDetectionResult[] = [];
    for (const [index, rawLine] of bulkText.split(/\r?\n/).entries()) {
      const trimmedLine = rawLine.trim();
      if (!trimmedLine || trimmedLine.startsWith("#")) continue;
      pendingRows.push({
        line: index + 1,
        key: `pending-${index + 1}`,
        endpoint: bulkProxyEndpoint(trimmedLine, index + 1),
        countryCode: "",
        countryName: "",
        status: "checking",
      });
    }
    return pendingRows;
  }, [bulkPending, bulkResult, bulkStage, bulkText]);
  const isBulkChecking =
    bulkPending && bulkStage === "checking" && !bulkResult;
  const visibleBulkDetectionResults = bulkResult || bulkProgressResults.length
    ? bulkDetectionResults
    : bulkPendingDetectionResults;
  const bulkDetectionCounts = useMemo(
    () =>
      visibleBulkDetectionResults.reduce(
        (counts, item) => {
          counts[item.status] += 1;
          return counts;
        },
        {
          checking: 0,
          healthy: 0,
          unhealthy: 0,
          duplicate: 0,
          failed: 0,
        },
      ),
    [visibleBulkDetectionResults],
  );
  function openBulkCreate() {
    setBulkResult(null);
    setBulkProgressResults([]);
    setBulkPreviewToken("");
    setBulkStage("");
    setBulkConfirmMode("");
    setBulkText("");
    setBulkDrawerOpen(true);
  }
  function openBatchRebind() {
    if (!selectedProxyIds.length) return;
    setRebindSourceIds([...selectedProxyIds]);
    setRebindMode("automatic");
    setRebindMappings({});
    setRebindResult(null);
    setRebindDrawerOpen(true);
  }
  function openEdit(row: IpProxy) {
    if (!row.id) return;
    setEditing(row);
    setForm({
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
    if (!editing?.id || !form.host.trim() || !form.port) return;
    setPending(true);
    try {
      const body = {
        protocol: form.protocol,
        host: form.host.trim(),
        port: Number(form.port),
        username: form.username || undefined,
        password: form.password || undefined,
        countryCode: form.countryCode.trim().toUpperCase() || null,
        provider: form.provider.trim() || undefined,
        enabled: form.enabled,
      };
      await apiRequest(`/api/ip-proxies/${editing.id}`, {
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

  function bulkImportRequestBody() {
    return {
      lines: bulkText.split(/\r?\n/),
      defaultProtocol: bulkDefaults.protocol,
      countryCode:
        bulkDefaults.countryCode.trim().toUpperCase() || undefined,
      provider: bulkDefaults.provider.trim() || undefined,
      enabled: bulkDefaults.enabled,
    };
  }

  async function previewBulkCreate() {
    if (!bulkLineCount || bulkLineCount > 1000) return;
    const requestId = crypto.randomUUID();
    const controller = new AbortController();
    const completion = { current: null as BulkPreviewData | null };
    bulkPreviewRequestRef.current = { requestId, controller };
    setBulkPending(true);
    setBulkStage("checking");
    setBulkResult(null);
    setBulkProgressResults([]);
    setBulkPreviewToken("");
    try {
      await apiNdjsonRequest<BulkPreviewStreamEvent>(
        "/api/ip-proxies/import-preview/stream",
        {
          method: "POST",
          body: JSON.stringify({
            ...bulkImportRequestBody(),
            requestId,
          }),
          signal: controller.signal,
        },
        (event) => {
          if (bulkPreviewRequestRef.current?.requestId !== requestId) return;
          if (event.type === "snapshot") {
            setBulkProgressResults(event.results);
            return;
          }
          if (event.type === "result") {
            setBulkProgressResults((current) =>
              upsertBulkPreviewResult(current, event.result),
            );
            return;
          }
          if (event.type === "error") {
            throw new Error(event.detail || "代理检测失败");
          }
          completion.current = event.data;
          setBulkProgressResults(event.data.results);
          setBulkResult({
            summary: event.data.summary,
            results: event.data.results,
          });
          setBulkPreviewToken(event.data.previewToken);
        },
      );
      if (!completion.current) throw new Error("代理检测连接提前结束");
      const { summary } = completion.current;
      if (!summary.failed && !summary.duplicate && !summary.unhealthy) {
        toast.success(`检测完成：${summary.healthy} 条代理健康，等待确认导入`);
      } else {
        toast.warning(
          `检测完成：健康 ${summary.healthy}，异常 ${summary.unhealthy}，重复 ${summary.duplicate}，格式失败 ${summary.failed}`,
        );
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      toast.error(caught instanceof Error ? caught.message : "代理检测失败");
    } finally {
      if (bulkPreviewRequestRef.current?.requestId === requestId) {
        bulkPreviewRequestRef.current = null;
        setBulkStage("");
        setBulkPending(false);
      }
    }
  }

  async function cancelBulkPreview() {
    const activeRequest = bulkPreviewRequestRef.current;
    if (!activeRequest || bulkStage !== "checking") return;
    const cancellation = apiRequest(
      `/api/ip-proxies/import-preview/${activeRequest.requestId}/cancel`,
      { method: "POST" },
    );
    activeRequest.controller.abort();
    bulkPreviewRequestRef.current = null;
    setBulkPending(false);
    setBulkStage("");
    setBulkResult(null);
    setBulkProgressResults([]);
    setBulkPreviewToken("");
    try {
      await cancellation;
      toast.info("已取消代理检测");
    } catch {
      toast.warning("页面已停止检测，服务端取消通知失败");
    }
  }

  async function confirmBulkCreate(importMode: "healthy" | "all") {
    if (!bulkResult || !bulkPreviewToken || bulkPending) return;
    setBulkPending(true);
    setBulkStage("importing");
    setBulkConfirmMode(importMode);
    try {
      const payload = await apiRequest("/api/ip-proxies/import-confirm", {
        method: "POST",
        body: JSON.stringify({
          ...bulkImportRequestBody(),
          previewToken: bulkPreviewToken,
          importMode,
        }),
      });
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        payload) as Record<string, unknown>;
      const summary = (data.summary || {}) as Record<string, unknown>;
      const created = Number(summary.created || 0);
      const skipped = Number(summary.skipped || 0);
      const duplicate = Number(summary.duplicate || 0);
      const failed = Number(summary.failed || 0);
      await load();
      if (!skipped && !duplicate && !failed) {
        toast.success(`已导入 ${created} 条代理`);
      } else {
        toast.warning(
          `导入完成：新增 ${created}，跳过异常 ${skipped}，重复 ${duplicate}，格式失败 ${failed}`,
        );
      }
      setBulkDrawerOpen(false);
      setBulkText("");
      setBulkResult(null);
      setBulkProgressResults([]);
      setBulkPreviewToken("");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "确认导入失败");
    } finally {
      setBulkStage("");
      setBulkConfirmMode("");
      setBulkPending(false);
    }
  }

  async function toggle(row: IpProxy) {
    if (!row.id) return;
    try {
      await apiRequest(`/api/ip-proxies/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled }),
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "更新状态失败");
    }
  }
  async function healthTest(row: IpProxy) {
    if (!row.id) return;
    setTestingIds((current) => [...current, row.id]);
    try {
      await apiRequest(`/api/ip-proxies/${row.id}/test`, {
        method: "POST",
      });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "健康检测失败");
    } finally {
      setTestingIds((current) => current.filter((id) => id !== row.id));
    }
  }
  async function batchHealthTest() {
    const proxyIds = [...selectedProxyIds];
    if (!proxyIds.length || batchAction) return;
    setBatchAction("test");
    setTestingIds((current) => Array.from(new Set([...current, ...proxyIds])));
    try {
      let healthy = 0;
      let unhealthy = 0;
      for (let index = 0; index < proxyIds.length; index += 100) {
        const payload = await apiRequest("/api/ip-proxies/test-batch", {
          method: "POST",
          body: JSON.stringify({
            proxyIds: proxyIds.slice(index, index + 100),
            source: "manual",
          }),
        });
        const data = ((payload as { data?: Record<string, unknown> }).data ||
          payload) as Record<string, unknown>;
        const summary = (data.summary || {}) as Record<string, unknown>;
        healthy += Number(summary.healthy || 0);
        unhealthy += Number(summary.unhealthy || 0);
      }
      await load();
      if (unhealthy) {
        toast.warning(`批量检测完成：健康 ${healthy}，异常 ${unhealthy}`);
      } else {
        toast.success(`批量检测完成：${healthy} 条代理健康`);
      }
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "批量检测失败");
    } finally {
      setTestingIds((current) =>
        current.filter((id) => !proxyIds.includes(id)),
      );
      setBatchAction("");
    }
  }
  async function batchSetEnabled(enabled: boolean) {
    const action = enabled ? "启用" : "停用";
    const batchActionName = enabled ? "enable" : "disable";
    const selectedRowsById = new Map(proxyOptions.map((row) => [row.id, row]));
    const proxyIds = selectedProxyIds.filter(
      (id) => selectedRowsById.get(id)?.enabled !== enabled,
    );
    const skipped = selectedProxyIds.length - proxyIds.length;
    if (!selectedProxyIds.length || batchAction) return;
    if (!proxyIds.length) {
      toast.info(`选中的代理已经全部${enabled ? "启用" : "停用"}`);
      return;
    }
    if (
      !enabled &&
      !(await confirmAction({
        title: `停用选中的 ${proxyIds.length} 条代理？`,
        description: "停用后不会参与自动分配，已有账号绑定不会自动迁移。",
        confirmText: "批量停用",
      }))
    )
      return;
    setBatchAction(batchActionName);
    try {
      const results = await Promise.allSettled(
        proxyIds.map((id) =>
          apiRequest(`/api/ip-proxies/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ enabled }),
          }),
        ),
      );
      const succeeded = results.filter(
        (result) => result.status === "fulfilled",
      ).length;
      const failedResults = results.filter(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      const failedReasons = Array.from(
        new Set(
          failedResults.map((result) =>
            result.reason instanceof Error
              ? result.reason.message
              : "请求失败",
          ),
        ),
      );
      await load();
      if (failedResults.length || skipped) {
        const details = [
          skipped ? `${skipped} 条状态未变化，已跳过` : "",
          failedResults.length
            ? `${failedResults.length} 条失败${failedReasons.length ? `：${failedReasons.slice(0, 2).join("；")}` : ""}`
            : "",
        ]
          .filter(Boolean)
          .join("；");
        toast.warning(`批量${action}完成：成功 ${succeeded} 条；${details}`);
      } else {
        toast.success(`已${action} ${succeeded} 条代理`);
      }
    } finally {
      setBatchAction("");
    }
  }
  async function batchRebind() {
    if (!rebindSourceIds.length || batchAction || !rebindAccountCount) return;
    if (rebindMode === "manual" && !manualRebindReady) {
      toast.warning("请为每个有账号绑定的源代理选择目标代理");
      return;
    }
    if (rebindMode === "automatic" && policy.allocationMode === "manual") {
      toast.warning("当前分配模式为仅手动分配，不能执行自动重绑");
      return;
    }
    if (
      !(await confirmAction({
        title: `重绑 ${rebindAccountCount} 个账号？`,
        description:
          rebindMode === "manual"
            ? "系统会按指定映射迁移账号；在线账号将先断开，已保存的会话不会删除。"
            : "系统会排除已选源代理，再按当前国家匹配和分配策略选择目标；在线账号将先断开。",
        confirmText: "确认重绑",
      }))
    )
      return;
    setBatchAction("rebind");
    setRebindResult(null);
    try {
      const payload = await apiRequest(
        "/api/ip-proxy-bindings/rebind-batch",
        {
          method: "POST",
          body: JSON.stringify({
            mode: rebindMode,
            sourceProxyIds: rebindSourceIds,
            mappings:
              rebindMode === "manual"
                ? rebindSourceRows
                    .filter(
                      (row) =>
                        row.bindingCount > 0 && rebindMappings[row.id],
                    )
                    .map((row) => ({
                      sourceProxyId: row.id,
                      targetProxyId: rebindMappings[row.id],
                    }))
                : [],
          }),
        },
      );
      const data = ((payload as { data?: Record<string, unknown> }).data ||
        payload) as Record<string, unknown>;
      const rawSummary = (data.summary || {}) as Record<string, unknown>;
      const summary: BatchRebindSummary = {
        sourceProxies: Number(rawSummary.sourceProxies || 0),
        accounts: Number(rawSummary.accounts || 0),
        migrated: Number(rawSummary.migrated || 0),
        failed: Number(rawSummary.failed || 0),
        emptySources: Number(rawSummary.emptySources || 0),
      };
      const results = Array.isArray(data.results)
        ? data.results.map((item) => {
            const row = item as Record<string, unknown>;
            return {
              bindingId: text(row, "bindingId"),
              accountId: text(row, "accountId"),
              accountName: text(row, "accountName"),
              accountPhone: formatPhoneDisplay(text(row, "accountPhone")),
              sourceProxyId: text(row, "sourceProxyId"),
              targetProxyId: text(row, "targetProxyId"),
              status:
                text(row, "status") === "success" ? "success" : "failed",
              error: text(row, "error"),
            } satisfies BatchRebindResult;
          })
        : [];
      await load();
      if (summary.failed) {
        setRebindResult({ summary, results });
        toast.warning(
          `批量重绑完成：成功 ${summary.migrated}，失败 ${summary.failed}`,
        );
      } else {
        setRebindDrawerOpen(false);
        toast.success(`已重绑 ${summary.migrated} 个账号`);
      }
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "批量重绑失败");
    } finally {
      setBatchAction("");
    }
  }
  async function batchDelete() {
    const proxyIds = [...selectedProxyIds];
    if (!proxyIds.length || batchAction) return;
    const selectedRowsById = new Map(proxyOptions.map((row) => [row.id, row]));
    const boundProxyIds = proxyIds.filter(
      (id) => (selectedRowsById.get(id)?.bindingCount || 0) > 0,
    );
    const boundAccountCount = boundProxyIds.reduce(
      (total, id) => total + (selectedRowsById.get(id)?.bindingCount || 0),
      0,
    );
    const boundProxyIdSet = new Set(boundProxyIds);
    const deletableIds = proxyIds.filter((id) => !boundProxyIdSet.has(id));
    if (!deletableIds.length) {
      toast.warning(
        `选中的 ${boundProxyIds.length} 条代理共绑定 ${boundAccountCount} 个账号，不能直接删除。请打开代理详情解除绑定后重试`,
      );
      return;
    }
    if (
      !(await confirmAction({
        title: `删除选中的 ${deletableIds.length} 条可删除代理？`,
        description: boundProxyIds.length
          ? `另有 ${boundProxyIds.length} 条代理仍绑定 ${boundAccountCount} 个账号，本次会自动跳过。删除后无法恢复。`
          : "删除后无法恢复。",
        confirmText: "批量删除",
        destructive: true,
      }))
    )
      return;
    setBatchAction("delete");
    try {
      const results = await Promise.allSettled(
        deletableIds.map((id) =>
          apiRequest(`/api/ip-proxies/${id}`, { method: "DELETE" }),
        ),
      );
      const deletedIds = deletableIds.filter(
        (_, index) => results[index]?.status === "fulfilled",
      );
      const failedResults = results.filter(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      const failedReasons = Array.from(
        new Set(
          failedResults.map((result) =>
            result.reason instanceof Error
              ? result.reason.message
              : "请求失败",
          ),
        ),
      );
      setSelectedProxyIds((current) =>
        current.filter((id) => !deletedIds.includes(id)),
      );
      await load();
      if (boundProxyIds.length || failedResults.length) {
        const details = [
          boundProxyIds.length
            ? `${boundProxyIds.length} 条仍有账号绑定，已跳过`
            : "",
          failedResults.length
            ? `${failedResults.length} 条删除失败${failedReasons.length ? `：${failedReasons.slice(0, 2).join("；")}` : ""}`
            : "",
        ]
          .filter(Boolean)
          .join("；");
        toast.warning(`已删除 ${deletedIds.length} 条；${details}`);
      } else {
        toast.success(`已删除 ${deletedIds.length} 条代理`);
      }
    } finally {
      setBatchAction("");
    }
  }
  async function remove(row: IpProxy) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除代理“${row.host}:${row.port}”？`,
        description: "删除后无法恢复；已有绑定时需先解绑账号。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/ip-proxies/${row.id}`, { method: "DELETE" });
      await load();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
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
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索主机、端口、国家、地区或供应商",
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
            <SearchableSelect
              ariaLabel="国家筛选"
              value={country}
              onValueChange={setCountry}
              className="w-44"
              searchPlaceholder="搜索国家、地区或代码"
              emptyText="没有匹配的国家或地区"
              options={[
                {
                  value: "all",
                  label: "全部国家",
                  keywords: "全部 all",
                  leading: <CountryFlag code="WW" />,
                },
                ...filterCountries.map((value) => ({
                  value,
                  label: `${countryDisplayName(value)} · ${value}`,
                  keywords: countryOptions.find((option) => option.value === value)?.keywords || value,
                  leading: <CountryFlag code={value} />,
                })),
              ]}
            />
            <SearchableSelect
              ariaLabel="供应商筛选"
              value={provider}
              onValueChange={setProvider}
              className="w-44"
              searchPlaceholder="搜索供应商"
              emptyText="没有匹配的供应商"
              options={[
                { value: "all", label: "全部供应商", keywords: "全部 all" },
                ...filterProviders.map((value) => ({
                  value,
                  label: value,
                  keywords: value,
                })),
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
        meta={
          selectedProxyIds.length
            ? `已选择 ${selectedProxyIds.length} 条代理`
            : `${total} 条代理`
        }
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    disabled={!selectedProxyIds.length || Boolean(batchAction)}
                  >
                    {batchAction ? (
                      <Spinner />
                    ) : (
                      <ListChecksIcon data-icon="inline-start" />
                    )}
                    批量操作
                    {selectedProxyIds.length
                      ? ` (${selectedProxyIds.length})`
                      : ""}
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuItem onSelect={() => void batchHealthTest()}>
                      <CircleGaugeIcon />
                      批量检测
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={openBatchRebind}>
                      <ArrowRightLeftIcon />
                      批量重绑
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => void batchSetEnabled(true)}
                    >
                      <PowerIcon />
                      批量启用
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => void batchSetEnabled(false)}
                    >
                      <PowerOffIcon />
                      批量停用
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={() => void batchDelete()}
                    >
                      <Trash2Icon />
                      批量删除
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            {canManage ? (
              <Button onClick={openBulkCreate}>
                <PlusIcon size={17} />
                批量添加
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
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />

      <ListTableCard>
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
          ) : rows.length ? (
            <div className="table-scroll">
              <Table layout="list">
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <Checkbox
                        aria-label="选择本页代理"
                        disabled={!canManage || !pageProxyIds.length}
                        checked={
                          allPageSelected
                            ? true
                            : somePageSelected
                              ? "indeterminate"
                              : false
                        }
                        onCheckedChange={(checked) =>
                          setSelectedProxyIds((current) =>
                            checked === true
                              ? Array.from(
                                  new Set([...current, ...pageProxyIds]),
                                )
                              : current.filter(
                                  (id) => !pageProxyIds.includes(id),
                                ),
                          )
                        }
                      />
                    </TableHead>
                    <ListSortableHead sortKey="id" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort} adaptive>代理</ListSortableHead>
                    <ListSortableHead sortKey="protocol" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>协议</ListSortableHead>
                    <ListSortableHead sortKey="countryCode" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>国家 / 地区</ListSortableHead>
                    <ListSortableHead sortKey="provider" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>供应商</ListSortableHead>
                    <TableHead>凭证</TableHead>
                    <ListSortableHead sortKey="healthStatus" activeSortKey={sortBy} sortOrder={sortOrder} onSort={changeSort}>健康状态</ListSortableHead>
                    <TableHead>绑定</TableHead>
                    <ListSortableHead sortKey="createdAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>创建时间</ListSortableHead>
                    <ListSortableHead sortKey="updatedAt" activeSortKey={sortBy} sortOrder={sortOrder} defaultOrder="desc" onSort={changeSort}>更新时间</ListSortableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.readKey}>
                      <TableCell>
                        <Checkbox
                          aria-label={`选择代理 ${row.host}:${row.port}`}
                          disabled={!canManage || !row.id}
                          checked={
                            Boolean(row.id) &&
                            selectedProxyIds.includes(row.id)
                          }
                          onCheckedChange={(checked) =>
                            row.id &&
                            setSelectedProxyIds((current) =>
                              checked === true
                                ? Array.from(new Set([...current, row.id]))
                                : current.filter((id) => id !== row.id),
                            )
                          }
                        />
                      </TableCell>
                      <TableCell primary>
                        <EntityPrimaryCell
                          title={`${row.host}:${row.port}`}
                          id={row.id}
                          status={{
                            ...proxyStatus(row),
                            details: [
                              { label: "延迟", value: row.latencyMs ? `${row.latencyMs} ms` : "-" },
                              { label: "国家", value: row.countryName || row.countryCode || "待自动检测" },
                              { label: "绑定数", value: row.bindingCount },
                            ],
                          }}
                        />
                      </TableCell>
                      <TableCell>{row.protocol.toUpperCase()}</TableCell>
                      <TableCell>
                        <div className="flex min-w-max flex-col items-center gap-1 text-center">
                          {row.countryCode ? (
                            <CountryDisplay
                              code={row.countryCode}
                              className="justify-center font-semibold"
                            />
                          ) : (
                            <strong>{row.countryName || "待自动检测"}</strong>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span className={row.provider ? "" : "text-muted-foreground"}>
                          {row.provider || "-"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="credential-cell">
                          <span>用户 {row.usernameMasked}</span>
                          <span>密码 {row.passwordMasked}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="health-cell">
                          <div className="health-cell__summary">
                            <Badge tone={proxyStatus(row).tone}>
                              {proxyStatus(row).label}
                            </Badge>
                            <span>
                              {row.latencyMs ? `${row.latencyMs} ms` : "-"}
                            </span>
                          </div>
                          <small title={row.lastError}>
                            {row.cooldownUntil
                              ? `冷却至 ${formatDateTime(row.cooldownUntil)}`
                              : row.lastError || formatDateTime(row.lastCheckedAt)}
                          </small>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {row.bindingCount}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(row.createdAt)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(row.updatedAt)}
                      </TableCell>
                      <TableCell>
                        <div className="flex min-w-max items-center justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!row.id}
                            onClick={() => setSelectedId(row.id)}
                          >
                            <EyeIcon />
                            详情
                          </Button>
                          {canManage ? (
                            <>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={
                                  !row.id ||
                                  !row.enabled ||
                                  testingIds.includes(row.id)
                                }
                                onClick={() => void healthTest(row)}
                              >
                                {testingIds.includes(row.id) ? (
                                  <LoaderCircleIcon className="spin" size={16} />
                                ) : null}
                                健康检测
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={!row.id}
                                onClick={() => openEdit(row)}
                              >
                                编辑
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={!row.id}
                                onClick={() => void toggle(row)}
                              >
                                {row.enabled ? "停用" : "启用"}
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
              title="没有匹配的代理"
              description="调整筛选条件，或添加新的 HTTP、HTTPS、SOCKS5 代理。"
            />
          )}
      </ListTableCard>

      <Drawer
        open={Boolean(selected)}
        onClose={() => {
          setSelectedId("");
        }}
        title="代理详情"
        description={
          selected
            ? `${selected.host}:${selected.port} · ${selected.id}`
            : "集中查看代理信息和健康状态。"
        }
        wide
      >
        {selected ? (
          <div className="grid gap-6 pb-6">
            <section className="grid gap-3">
              <div>
                <h3 className="text-sm font-semibold">基本信息</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  代理端点、来源标识和访问凭证。
                </p>
              </div>
              <div className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
                <div className="cell-main">
                  <span>代理地址</span>
                  <strong>{selected.host}:{selected.port}</strong>
                </div>
                <div className="cell-main">
                  <span>系统 ID</span>
                  <strong>{selected.id}</strong>
                </div>
                <div className="cell-main">
                  <span>协议</span>
                  <strong>{selected.protocol.toUpperCase()}</strong>
                </div>
                <div className="cell-main">
                  <span>国家 / 地区</span>
                  {selected.countryCode ? (
                    <CountryDisplay
                      code={selected.countryCode}
                      className="justify-start font-semibold"
                    />
                  ) : (
                    <strong>待自动检测</strong>
                  )}
                </div>
                <div className="cell-main">
                  <span>供应商</span>
                  <strong>{selected.provider || "-"}</strong>
                </div>
                <div className="cell-main">
                  <span>访问凭证</span>
                  <strong>用户 {selected.usernameMasked}</strong>
                  <span>密码 {selected.passwordMasked}</span>
                </div>
                <div className="cell-main">
                  <span>创建时间</span>
                  <strong>{formatDateTime(selected.createdAt)}</strong>
                </div>
              </div>
            </section>

            <section className="grid gap-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-sm font-semibold">健康状态</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    首次导入检测与网关实际使用回写的最新结果。
                  </p>
                </div>
                {canManage ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        !selected.enabled || testingIds.includes(selected.id)
                      }
                      onClick={() => void healthTest(selected)}
                    >
                      {testingIds.includes(selected.id) ? (
                        <LoaderCircleIcon className="spin" />
                      ) : (
                        <CircleGaugeIcon />
                      )}
                      健康检测
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSelectedId("");
                        openEdit(selected);
                      }}
                    >
                      编辑代理
                    </Button>
                  </div>
                ) : null}
              </div>
              <div className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
                <div className="cell-main">
                  <span>当前状态</span>
                  <Badge tone={proxyStatus(selected).tone}>
                    {proxyStatus(selected).label}
                  </Badge>
                </div>
                <div className="cell-main">
                  <span>延迟</span>
                  <strong>{selected.latencyMs ? `${selected.latencyMs} ms` : "-"}</strong>
                </div>
                <div className="cell-main">
                  <span>最近检测</span>
                  <strong>{formatDateTime(selected.lastCheckedAt)}</strong>
                </div>
                <div className="cell-main">
                  <span>结果来源</span>
                  <strong>
                    {selected.lastCheckSource === "gateway"
                      ? "网关实际使用"
                      : selected.lastCheckSource === "import"
                        ? "首次导入检测"
                        : selected.lastCheckSource === "manual"
                          ? "手动检测"
                          : selected.lastCheckSource || "-"}
                  </strong>
                </div>
                <div className="cell-main">
                  <span>连续失败</span>
                  <strong>{selected.consecutiveFailures}</strong>
                </div>
                <div className="cell-main">
                  <span>冷却状态</span>
                  <strong>
                    {selected.cooldownUntil
                      ? `至 ${formatDateTime(selected.cooldownUntil)}`
                      : "未冷却"}
                  </strong>
                </div>
                <div className="cell-main sm:col-span-2">
                  <span>最新异常</span>
                  <strong className={selected.lastError ? "text-destructive" : ""}>
                    {selected.lastError || "无异常"}
                  </strong>
                </div>
              </div>
            </section>

          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={rebindDrawerOpen}
        onClose={() => {
          if (batchAction !== "rebind") setRebindDrawerOpen(false);
        }}
        title="批量重绑代理"
        description={`已选择 ${rebindSourceRows.length} 个源代理，共 ${rebindAccountCount} 个账号。`}
        footer={
          <>
            <Button
              variant="outline"
              disabled={batchAction === "rebind"}
              onClick={() => setRebindDrawerOpen(false)}
            >
              取消
            </Button>
            <Button
              disabled={
                batchAction === "rebind" ||
                !rebindAccountCount ||
                (rebindMode === "manual" && !manualRebindReady) ||
                (rebindMode === "automatic" &&
                  (policyLoading ||
                    Boolean(policyError) ||
                    policy.allocationMode === "manual"))
              }
              onClick={() => void batchRebind()}
            >
              {batchAction === "rebind" ? (
                <Spinner />
              ) : (
                <ArrowRightLeftIcon />
              )}
              确认重绑
            </Button>
          </>
        }
      >
        <DrawerFormLayout>
          <DrawerFormSection
            title="重绑方式"
            description="手动为每个源代理指定目标，或让系统按当前分配策略自动选择。"
          >
            <DrawerFormField required label="选择模式" align="start">
              <div className="grid min-w-0 gap-2">
                <DrawerChoiceGroup
                  label="批量重绑模式"
                  value={rebindMode}
                  onChange={(value) => {
                    setRebindMode(value as RebindMode);
                    setRebindResult(null);
                  }}
                  options={[
                    { value: "automatic", label: "自动重绑模式" },
                    { value: "manual", label: "一对一模式" },
                  ]}
                />
                <p className="text-xs leading-5 text-muted-foreground">
                  {rebindMode === "manual"
                    ? "每个源代理下的全部账号，统一迁移到你为它指定的目标代理。"
                    : "排除本次选中的全部源代理，使用其他可用代理并遵循当前分配策略。"}
                </p>
              </div>
            </DrawerFormField>
          </DrawerFormSection>

          {rebindMode === "manual" ? (
            <DrawerFormSection
              title="代理映射"
              description="仅有账号绑定的源代理需要指定目标；目标代理必须已启用且不在冷却中。"
            >
              <div className="grid gap-3">
                {rebindSourceRows.map((source) => {
                  const targetOptions = proxyOptions
                    .filter(
                      (target) =>
                        target.id &&
                        target.id !== source.id &&
                        proxyAvailableForRebind(target),
                    )
                    .map((target) => ({
                      value: target.id,
                      label: `${target.host}:${target.port}${target.countryCode ? ` · ${countryDisplayName(target.countryCode)}` : ""}`,
                      keywords: `${target.host} ${target.port} ${target.countryCode} ${target.provider}`,
                      leading: <CountryFlag code={target.countryCode || "WW"} />,
                    }));
                  return (
                    <div
                      key={source.id}
                      className="grid gap-3 rounded-xl border p-3"
                    >
                      <div className="flex min-w-0 items-center justify-between gap-3">
                        <div className="cell-main min-w-0">
                          <strong>{source.host}:{source.port}</strong>
                          <span>{source.id}</span>
                        </div>
                        <Badge tone={source.bindingCount ? "neutral" : "warning"}>
                          {source.bindingCount} 个账号
                        </Badge>
                      </div>
                      {source.bindingCount ? (
                        <SearchableSelect
                          ariaLabel={`源代理 ${source.host}:${source.port} 的目标代理`}
                          className="w-full"
                          value={rebindMappings[source.id] || ""}
                          placeholder="选择目标代理"
                          searchPlaceholder="搜索主机、国家或供应商"
                          emptyText="没有其他可用代理"
                          onValueChange={(targetId) =>
                            setRebindMappings((current) => ({
                              ...current,
                              [source.id]: targetId,
                            }))
                          }
                          options={targetOptions}
                        />
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          当前没有绑定账号，无需指定目标代理。
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </DrawerFormSection>
          ) : (
            <DrawerFormSection
              title="自动分配规则"
              description="自动重绑与账号首次分配使用同一套国家匹配和容量规则。"
            >
              <div className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
                <div className="cell-main">
                  <span>国家匹配</span>
                  <strong>
                    {policy.countryMatch === "visitor_country"
                      ? "访问国家优先"
                      : "号码国家优先"}
                  </strong>
                </div>
                <div className="cell-main">
                  <span>分配模式</span>
                  <strong>{allocationModeLabels[policy.allocationMode]}</strong>
                </div>
                <div className="cell-main">
                  <span>每个 IP 上限</span>
                  <strong>{policy.maxAccountsPerIp} 个账号</strong>
                </div>
                <div className="cell-main">
                  <span>当前可见目标池</span>
                  <strong>{automaticRebindTargets.length} 个代理</strong>
                </div>
              </div>
              {policy.allocationMode === "manual" ? (
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
                  当前分配模式为“仅手动分配”，请改用一对一模式，或先修改分配策略。
                </div>
              ) : (
                <p className="text-xs leading-5 text-muted-foreground">
                  同国家代理只做优先匹配；没有同国家代理时会回退到其他国家，再按
                  {allocationModeLabels[policy.allocationMode]}选择目标。
                </p>
              )}
            </DrawerFormSection>
          )}

          <DrawerFormSection title="执行说明">
            <div className="grid gap-2 rounded-xl border bg-muted/30 p-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">源代理</span>
                <strong>{rebindSourceRows.length} 个</strong>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">待重绑账号</span>
                <strong>{rebindAccountCount} 个</strong>
              </div>
              <p className="mt-1 border-t pt-3 text-xs leading-5 text-muted-foreground">
                在线账号会先断开连接再更新代理，已保存的 WhatsApp 会话不会删除；重绑完成后可正常重新连接。
              </p>
            </div>
          </DrawerFormSection>

          {rebindResult?.summary.failed ? (
            <DrawerFormSection title="失败明细">
              <div className="grid gap-2 rounded-xl border border-destructive/20 bg-destructive/5 p-3">
                <strong className="text-sm text-destructive">
                  成功 {rebindResult.summary.migrated} 个，失败 {rebindResult.summary.failed} 个
                </strong>
                {rebindResult.results
                  .filter((item) => item.status === "failed")
                  .slice(0, 20)
                  .map((item) => (
                    <div
                      key={item.bindingId}
                      className="grid gap-0.5 border-t border-destructive/10 pt-2 text-xs"
                    >
                      <span className="font-medium">
                        {item.accountName || item.accountPhone || item.accountId || "账号已不存在"}
                      </span>
                      <span className="text-destructive">{item.error}</span>
                    </div>
                  ))}
              </div>
            </DrawerFormSection>
          ) : null}
        </DrawerFormLayout>
      </Drawer>

      <Drawer
        open={policyDrawerOpen}
        onClose={() => !policySaving && setPolicyDrawerOpen(false)}
        title="账号 IP 分配策略"
        description="设置账号首次分配代理时的隔离程度、国家匹配、容量限制和健康保护。"
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
          <DrawerFormLayout>
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
            <DrawerFormSection title="分配规则">
              <DrawerFormField required label="国家匹配" hint={countryDescriptions[policy.countryMatch]}>
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
                    { value: "visitor_country", label: "访问国家优先（推荐）" },
                    { value: "phone_country", label: "号码国家优先" },
                  ]}
                />
              </DrawerFormField>
              <DrawerFormField required label="分配模式" hint={allocationDescriptions[policy.allocationMode]}>
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
              </DrawerFormField>
              <DrawerFormField
                required
                label="每个 IP 最多账号数"
                hint={policy.allocationMode === "strict_one_to_one" ? "严格 1:1 模式固定按 1 个账号执行。" : "达到上限的 IP 不再参与自动分配。"}
              >
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
              </DrawerFormField>
            </DrawerFormSection>
            <DrawerFormSection title="健康与绑定">
              <DrawerFormField
                required
                label="连续失败次数"
                hint="网关实际使用连续失败达到该次数后，代理进入冷却；认证失败会立即隔离。"
              >
                <Input
                  type="number"
                  min="1"
                  max="10"
                  value={policy.failureThreshold}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      failureThreshold: Math.max(
                        1,
                        Math.min(10, Number(event.target.value) || 1),
                      ),
                    }))
                  }
                />
              </DrawerFormField>
              <DrawerFormField
                required
                label="冷却时间（秒）"
                hint="冷却期间不参与任何自动分配；到期后以最低优先级试用，成功即恢复。"
              >
                <Input
                  type="number"
                  min="60"
                  max="86400"
                  value={policy.cooldownSeconds}
                  disabled={!canManage || policySaving || Boolean(policyError)}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      cooldownSeconds: Math.max(
                        60,
                        Math.min(86400, Number(event.target.value) || 60),
                      ),
                    }))
                  }
                />
              </DrawerFormField>
              <DrawerFormField label="保持固定绑定" hint="账号成功分配后持续使用同一 IP，除非管理员手动解绑。">
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
              </DrawerFormField>
            </DrawerFormSection>
          </DrawerFormLayout>
        )}
      </Drawer>

      <Drawer
        open={bulkDrawerOpen}
        onClose={() => !bulkPending && setBulkDrawerOpen(false)}
        title="批量添加 IP 代理"
        description="先检测代理的 WhatsApp 可达性与出口国家，确认结果后再选择导入正常代理或导入全部。"
        footer={
          <>
            <Button
              variant="outline"
              disabled={bulkPending && bulkStage !== "checking"}
              onClick={() => {
                if (isBulkChecking) {
                  void cancelBulkPreview();
                  return;
                }
                setBulkDrawerOpen(false);
              }}
            >
              {isBulkChecking ? "取消检测" : "取消"}
            </Button>
            {bulkResult ? (
              <>
                <Button
                  variant="outline"
                  disabled={bulkPending}
                  onClick={() => {
                    setBulkResult(null);
                    setBulkProgressResults([]);
                    setBulkPreviewToken("");
                  }}
                >
                  重新填写
                </Button>
                <Button
                  disabled={bulkPending || !bulkResult.summary.healthy}
                  onClick={() => void confirmBulkCreate("healthy")}
                >
                  {bulkPending && bulkConfirmMode === "healthy" ? (
                    <LoaderCircleIcon className="spin" size={17} />
                  ) : null}
                  导入正常（{bulkResult.summary.healthy}）
                </Button>
                <Button
                  variant="outline"
                  disabled={bulkPending || !bulkResult.summary.candidates}
                  onClick={() => void confirmBulkCreate("all")}
                >
                  {bulkPending && bulkConfirmMode === "all" ? (
                    <LoaderCircleIcon className="spin" size={17} />
                  ) : null}
                  导入全部（{bulkResult.summary.candidates}）
                </Button>
              </>
            ) : (
              <Button
                disabled={
                  bulkPending || !bulkLineCount || bulkLineCount > 1000
                }
                onClick={() => void previewBulkCreate()}
              >
                {bulkPending ? (
                  <LoaderCircleIcon className="spin" size={17} />
                ) : (
                  <CircleGaugeIcon size={17} />
                )}
                {bulkPending ? "正在检测" : "开始检测"}
              </Button>
            )}
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <DrawerFieldLabel required>代理列表</DrawerFieldLabel>
            <Textarea
              className="min-h-64 resize-y font-mono"
              value={bulkText}
              disabled={bulkPending || Boolean(bulkResult)}
              onChange={(event) => {
                setBulkText(event.target.value);
                setBulkResult(null);
                setBulkProgressResults([]);
                setBulkPreviewToken("");
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

          <div className="form-grid">
            <label className="field">
              <DrawerFieldLabel required>默认协议</DrawerFieldLabel>
              <SelectField
                value={bulkDefaults.protocol}
                disabled={bulkPending || Boolean(bulkResult)}
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
            <div className="field">
              <DrawerFieldLabel>国家 / 地区</DrawerFieldLabel>
              <SearchableSelect
                value={bulkDefaults.countryCode}
                disabled={bulkPending || Boolean(bulkResult)}
                onValueChange={(value) =>
                  setBulkDefaults((current) => ({
                    ...current,
                    countryCode: value,
                  }))
                }
                options={optionalProxyCountryOptions}
                placeholder="选择国家或地区"
                searchPlaceholder="搜索国家、地区或代码"
                emptyText="没有匹配的国家或地区"
                ariaLabel="批量导入代理国家"
              />
            </div>
            <label className="field">
              <DrawerFieldLabel>代理供应商</DrawerFieldLabel>
              <Input
                value={bulkDefaults.provider}
                disabled={bulkPending || Boolean(bulkResult)}
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
              disabled={bulkPending || Boolean(bulkResult)}
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

          {isBulkChecking || bulkResult ? (
            <div className="grid gap-4 rounded-lg border bg-muted/30 p-4">
              <div>
                <div className="flex items-center gap-2">
                  {isBulkChecking ? (
                    <LoaderCircleIcon className="spin text-primary" size={18} />
                  ) : null}
                  <strong>
                    {isBulkChecking
                      ? "正在检测（尚未导入）"
                      : "检测结果（尚未导入）"}
                  </strong>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {isBulkChecking ? (
                    <>
                      共 {visibleBulkDetectionResults.length} 条 · 正在检查 WhatsApp
                      可达性并识别出口国家
                    </>
                  ) : bulkResult ? (
                    <>
                      共 {bulkResult.summary.total} 条 · 可确认 {bulkResult.summary.candidates}
                      条 · 重复 {bulkResult.summary.duplicate} 条 · 格式失败 {bulkResult.summary.failed} 条
                    </>
                  ) : null}
                </p>
              </div>

              {visibleBulkDetectionResults.length ? (
                <div className="grid gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    {isBulkChecking ? (
                      <>
                        <Badge tone="warning">
                          <LoaderCircleIcon className="spin" size={12} />
                          检测中 {bulkDetectionCounts.checking}
                        </Badge>
                        {bulkDetectionCounts.healthy ? (
                          <Badge tone="success">
                            健康 {bulkDetectionCounts.healthy}
                          </Badge>
                        ) : null}
                        {bulkDetectionCounts.unhealthy ? (
                          <Badge tone="danger">
                            异常 {bulkDetectionCounts.unhealthy}
                          </Badge>
                        ) : null}
                        {bulkDetectionCounts.duplicate ? (
                          <Badge tone="neutral">
                            重复 {bulkDetectionCounts.duplicate}
                          </Badge>
                        ) : null}
                        {bulkDetectionCounts.failed ? (
                          <Badge tone="danger">
                            格式失败 {bulkDetectionCounts.failed}
                          </Badge>
                        ) : null}
                        <span className="text-xs text-muted-foreground">
                          每条代理完成后会在当前列表中实时更新
                        </span>
                      </>
                    ) : bulkResult ? (
                      <>
                        <Badge tone="success">
                          健康 {bulkResult.summary.healthy}
                        </Badge>
                        <Badge
                          tone={
                            bulkResult.summary.unhealthy ? "danger" : "neutral"
                          }
                        >
                          异常 {bulkResult.summary.unhealthy}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          检测已完成，请选择导入范围
                        </span>
                      </>
                    ) : null}
                  </div>

                  <div className="overflow-hidden rounded-lg border bg-background">
                    <div className="grid grid-cols-[minmax(0,1fr)_8rem_7rem] gap-3 border-b bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground">
                      <span>代理地址</span>
                      <span>国家 / 地区</span>
                      <span>健康状态</span>
                    </div>
                    <div className="max-h-72 divide-y overflow-y-auto">
                      {visibleBulkDetectionResults.map((item) => (
                        <div
                          className="grid grid-cols-[minmax(0,1fr)_8rem_7rem] items-center gap-3 px-3 py-2.5 text-sm"
                          key={item.key}
                        >
                          <div className="min-w-0">
                            <strong className="block truncate">
                              {item.endpoint}
                            </strong>
                            <span
                              className="block truncate text-xs text-muted-foreground"
                              title={item.error || undefined}
                            >
                              第 {item.line} 行
                              {item.error ? ` · ${item.error}` : ""}
                            </span>
                          </div>
                          <div className="min-w-0">
                            {item.countryCode ? (
                              <CountryDisplay
                                code={item.countryCode}
                                className="justify-start"
                              />
                            ) : (
                              <div className="flex items-center gap-2 text-muted-foreground">
                                <CountryFlag code="WW" />
                                <span>
                                  {item.status === "checking"
                                    ? "识别中"
                                    : "未识别"}
                                </span>
                              </div>
                            )}
                          </div>
                          <div className="grid justify-items-start gap-1">
                            <Badge
                              tone={
                                item.status === "checking"
                                  ? "warning"
                                  : item.status === "healthy"
                                  ? "success"
                                  : item.status === "duplicate"
                                  ? "neutral"
                                  : "danger"
                              }
                            >
                              {item.status === "checking" ? (
                                <LoaderCircleIcon className="spin" size={12} />
                              ) : null}
                              {item.status === "checking"
                                ? "检测中"
                                : item.status === "healthy"
                                ? "健康"
                                : item.status === "unhealthy"
                                ? "异常"
                                : item.status === "duplicate"
                                ? "重复"
                                : "格式失败"}
                            </Badge>
                            {item.latencyMs !== undefined &&
                            item.latencyMs !== null ? (
                              <span className="text-xs text-muted-foreground">
                                {item.latencyMs} ms
                              </span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}

              {bulkResult?.results.some((item) => item.status !== "checked") ? (
                <div className="grid gap-2">
                  <span className="text-sm font-medium">不可导入明细</span>
                  <div className="max-h-44 space-y-2 overflow-y-auto">
                    {bulkResult.results
                      .filter((item) => item.status !== "checked")
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
              disabled={pending || !form.host.trim() || !form.port}
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
            <label className="field">
              <DrawerFieldLabel required>协议</DrawerFieldLabel>
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
              <DrawerFieldLabel required>端口</DrawerFieldLabel>
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
              <DrawerFieldLabel required>主机地址</DrawerFieldLabel>
              <Input
                value={form.host}
                onChange={(event) => updateForm("host", event.target.value)}
                placeholder="proxy.example.com 或 203.0.113.10"
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>用户名（留空不修改）</DrawerFieldLabel>
              <Input
                value={form.username}
                onChange={(event) => updateForm("username", event.target.value)}
                autoComplete="off"
                placeholder={editing?.usernameMasked || "未设置"}
              />
            </label>
            <label className="field">
              <DrawerFieldLabel>密码（留空不修改）</DrawerFieldLabel>
              <Input
                type="password"
                value={form.password}
                onChange={(event) => updateForm("password", event.target.value)}
                autoComplete="new-password"
                placeholder={editing?.passwordMasked || "未设置"}
              />
            </label>
            <div className="field">
              <DrawerFieldLabel>国家 / 地区</DrawerFieldLabel>
              <SearchableSelect
                value={form.countryCode}
                onValueChange={(value) => updateForm("countryCode", value)}
                options={optionalProxyCountryOptions}
                placeholder="选择国家或地区"
                searchPlaceholder="搜索国家、地区或代码"
                emptyText="没有匹配的国家或地区"
                ariaLabel="代理国家"
              />
            </div>
            <label className="field">
              <DrawerFieldLabel>代理供应商</DrawerFieldLabel>
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
