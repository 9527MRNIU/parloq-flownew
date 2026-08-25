import {
  LoaderCircleIcon,
  PlayCircleIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  ShoppingCartIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  DatePickerField,
  EmptyState,
  Input,
  Modal,
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
import {
  ListPagination,
  ListSortableHead,
  ListTableCard,
  ListToolbar,
  StandardListPage,
  type ListSortOrder,
} from "../components/list-page";
import { useAuth } from "../auth/AuthContext";
import { entityRowKey, snowflakeId } from "../lib/entity-identifiers";
import {
  EntityPrimaryCell,
  type EntityStatusMeta,
} from "../components/entity-primary-cell";
import {
  DrawerFormField,
  DrawerFormLayout,
  DrawerFormSection,
} from "../components/drawer-form";

type DomainRow = {
  id: string;
  readKey: string;
  hostname: string;
  enabled: boolean;
  dnsStatus: string;
  sslStatus: string;
  boundCount: number;
  acquisitionType: string;
  managementMode: string;
  hostingStatus: string;
  registrationStatus: string;
  expiresAt?: string;
  channelSelectable: boolean;
  connection: {
    cname?: { name?: string; target?: string };
    txt?: { name?: string; value?: string };
  };
  lastVerifiedAt?: string;
  lastError?: string;
  createdAt?: string;
  onboarding: {
    status: string;
    stage: string;
    message?: string;
    nameservers: string[];
    zoneStatus?: string;
    canContinue: boolean;
    lastAttemptedAt?: string;
    completedAt?: string;
  };
};
type DomainOrderRow = {
  id: string;
  readKey: string;
  hostname: string;
  years: number;
  amount: number;
  currency: string;
  status: string;
  provider: string;
  autoRenew: boolean;
  failureReason?: string;
  domainId?: string;
  allowedActions: {
    mockPayment: boolean;
    provision: boolean;
    cancel: boolean;
    delete: boolean;
  };
  createdAt?: string;
  updatedAt?: string;
};
type CloudflareDomainRow = {
  id: string;
  readKey: string;
  hostname: string;
  status: string;
  paused: boolean;
  phishingDetected: boolean;
  source: "system_purchase" | "system_import" | "account_existing";
  onboardingStatus: string;
  systemDomainId?: string;
  createdAt?: string;
  updatedAt?: string;
};
type NameSiloDomainRow = {
  id: string;
  readKey: string;
  hostname: string;
  source: "system_purchase" | "system_order" | "account_existing";
  providerOwned: boolean;
  providerStatus: string;
  onboardingStatus: string;
  createdAt?: string;
  updatedAt?: string;
  expiresAt?: string;
  systemDomainId?: string;
  order?: DomainOrderRow;
};
type SystemDomainSortBy =
  | "id"
  | "source"
  | "ready"
  | "expiresAt"
  | "lastVerifiedAt"
  | "onboardingStatus";
type CloudflareDomainSortBy =
  | "id"
  | "source"
  | "providerStatus"
  | "onboardingStatus"
  | "createdAt"
  | "updatedAt";
type NameSiloDomainSortBy =
  | "id"
  | "source"
  | "providerStatus"
  | "createdAt"
  | "updatedAt"
  | "expiresAt"
  | "orderStatus"
  | "onboardingStatus";
type DomainSearchOption = {
  domain: string;
  registrationPrice: number;
  renewalPrice: number | null;
  currency: string;
  years: number;
};
type DomainSearchState = {
  searchId: string;
  label: string;
  years: number;
  status: "running" | "completed" | "failed";
  options: DomainSearchOption[];
  partial: boolean;
  searchedCount: number;
  skippedCount: number;
  candidateCount: number;
  error?: string;
};
type BaoTaDomainPolicy = {
  cdnEnabled: boolean;
  ccEnabled: boolean;
  chinaBlocked: boolean;
};
type BaoTaFirewallCapability = {
  status: "available" | "unavailable" | "unknown";
  checkedAt?: string;
};
const defaultBaoTaDomainPolicy: BaoTaDomainPolicy = {
  cdnEnabled: true,
  ccEnabled: false,
  chinaBlocked: true,
};

function baoTaSettings(input: unknown): {
  policy: BaoTaDomainPolicy;
  capability: BaoTaFirewallCapability;
  configured: boolean;
  enabled: boolean;
} {
  const row = (input ?? {}) as Record<string, unknown>;
  const settings = (row.settings ?? {}) as Record<string, unknown>;
  const rawPolicy = (settings.domainPolicy ?? {}) as Record<string, unknown>;
  const rawCapability = (settings.nginxFirewallPlugin ?? {}) as Record<string, unknown>;
  const statusValue = String(rawCapability.status || "unknown");
  return {
    policy: {
      cdnEnabled: Boolean(rawPolicy.cdnEnabled ?? defaultBaoTaDomainPolicy.cdnEnabled),
      ccEnabled: Boolean(rawPolicy.ccEnabled ?? defaultBaoTaDomainPolicy.ccEnabled),
      chinaBlocked: Boolean(rawPolicy.chinaBlocked ?? defaultBaoTaDomainPolicy.chinaBlocked),
    },
    capability: {
      status: statusValue === "available" || statusValue === "unavailable"
        ? statusValue
        : "unknown",
      checkedAt: String(rawCapability.checkedAt || ""),
    },
    configured: Boolean(row.configured),
    enabled: Boolean(row.enabled),
  };
}
const get = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
function normalize(input: unknown): DomainRow {
  const row = input as Record<string, unknown>;
  const onboarding = (row.onboarding && typeof row.onboarding === "object"
    ? row.onboarding
    : {}) as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "domain", get(row, "hostname", "domain")),
    hostname: get(row, "hostname", "domain"),
    enabled: Boolean(row.enabled ?? true),
    dnsStatus: get(row, "dnsStatus", "dns_status") || "pending",
    sslStatus: get(row, "sslStatus", "ssl_status") || "pending",
    boundCount: Number(row.boundChannelCount ?? row.bound_channel_count ?? 0),
    acquisitionType: get(row, "acquisitionType", "acquisition_type") || "connected",
    managementMode: get(row, "managementMode", "management_mode") || "external",
    hostingStatus: get(row, "hostingStatus", "hosting_status") || "pending",
    registrationStatus: get(row, "registrationStatus", "registration_status") || "active",
    expiresAt: get(row, "expiresAt", "expires_at"),
    channelSelectable: Boolean(row.channelSelectable ?? row.channel_selectable),
    connection: (row.connection && typeof row.connection === "object"
      ? row.connection
      : {}) as DomainRow["connection"],
    lastVerifiedAt: get(row, "lastVerifiedAt", "last_verified_at"),
    lastError: get(row, "lastError", "last_error"),
    createdAt: get(row, "createdAt", "created_at"),
    onboarding: {
      status: get(onboarding, "status") || "idle",
      stage: get(onboarding, "stage") || "not_started",
      message: get(onboarding, "message"),
      nameservers: Array.isArray(onboarding.nameservers)
        ? onboarding.nameservers.map(String)
        : [],
      zoneStatus: get(onboarding, "zoneStatus", "zone_status"),
      canContinue: Boolean(onboarding.canContinue ?? onboarding.can_continue ?? true),
      lastAttemptedAt: get(onboarding, "lastAttemptedAt", "last_attempted_at"),
      completedAt: get(onboarding, "completedAt", "completed_at"),
    },
  };
}
function normalizeOrder(input: unknown): DomainOrderRow {
  const row = input as Record<string, unknown>;
  const allowed = (row.allowedActions && typeof row.allowedActions === "object"
    ? row.allowedActions
    : row.allowed_actions || {}) as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  return {
    id,
    readKey: entityRowKey(row, id, "domain-order", `${get(row, "hostname")}:${get(row, "createdAt", "created_at")}`),
    hostname: get(row, "hostname"),
    years: Number(row.years || 1),
    amount: Number(row.amount || 0),
    currency: get(row, "currency") || "USD",
    status: get(row, "status") || "pending_payment",
    provider: get(row, "provider"),
    autoRenew: Boolean(row.autoRenew ?? row.auto_renew),
    failureReason: get(row, "failureReason", "failure_reason"),
    domainId: snowflakeId(row, "domainId", "domain_id"),
    allowedActions: {
      mockPayment: Boolean(allowed.mockPayment ?? allowed.mock_payment),
      provision: Boolean(allowed.provision),
      cancel: Boolean(allowed.cancel),
      delete: Boolean(allowed.delete),
    },
    createdAt: get(row, "createdAt", "created_at"),
    updatedAt: get(row, "updatedAt", "updated_at"),
  };
}
function normalizeCloudflareDomain(input: unknown): CloudflareDomainRow {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  const hostname = get(row, "hostname", "name");
  const source = get(row, "source");
  return {
    id,
    readKey: entityRowKey(row, id, "cloudflare-domain", hostname),
    hostname,
    status: get(row, "status") || "unknown",
    paused: Boolean(row.paused),
    phishingDetected: Boolean(row.phishingDetected ?? row.phishing_detected),
    source: source === "system_purchase"
      ? "system_purchase"
      : source === "system_import"
        ? "system_import"
        : "account_existing",
    onboardingStatus: get(row, "onboardingStatus", "onboarding_status"),
    systemDomainId: snowflakeId(row, "systemDomainId", "system_domain_id") || undefined,
    createdAt: get(row, "createdAt", "created_at"),
    updatedAt: get(row, "updatedAt", "updated_at"),
  };
}
function normalizeNameSiloDomain(input: unknown): NameSiloDomainRow {
  const row = input as Record<string, unknown>;
  const id = snowflakeId(row, "id");
  const hostname = get(row, "hostname", "domain");
  const orderValue = row.order && typeof row.order === "object" ? row.order : null;
  return {
    id,
    readKey: entityRowKey(row, id, "namesilo-domain", hostname),
    hostname,
    source: row.source === "system_purchase"
      ? "system_purchase"
      : row.source === "system_order"
        ? "system_order"
        : "account_existing",
    providerOwned: Boolean(row.providerOwned ?? row.provider_owned),
    providerStatus: get(row, "providerStatus", "provider_status") || "unknown",
    onboardingStatus: get(row, "onboardingStatus", "onboarding_status"),
    createdAt: get(row, "createdAt", "created_at"),
    updatedAt: get(row, "updatedAt", "updated_at"),
    expiresAt: get(row, "expiresAt", "expires_at"),
    systemDomainId: snowflakeId(row, "systemDomainId", "system_domain_id") || undefined,
    order: orderValue ? normalizeOrder(orderValue) : undefined,
  };
}
function normalizeSearch(input: unknown): DomainSearchState {
  const row = (input && typeof input === "object" ? input : {}) as Record<string, unknown>;
  const options = Array.isArray(row.options) ? row.options : [];
  return {
    searchId: get(row, "searchId", "search_id"),
    label: get(row, "label"),
    years: Number(row.years || 1),
    status: ["running", "completed", "failed"].includes(String(row.status))
      ? String(row.status) as DomainSearchState["status"]
      : "failed",
    options: options.map((value) => {
      const option = value as Record<string, unknown>;
      const renewal = option.renewalPrice ?? option.renewal_price;
      return {
        domain: get(option, "domain"),
        registrationPrice: Number(option.registrationPrice ?? option.registration_price ?? 0),
        renewalPrice: renewal == null ? null : Number(renewal),
        currency: get(option, "currency") || "USD",
        years: Number(option.years || row.years || 1),
      };
    }),
    partial: Boolean(row.partial),
    searchedCount: Number(row.searchedCount ?? row.searched_count ?? 0),
    skippedCount: Number(row.skippedCount ?? row.skipped_count ?? 0),
    candidateCount: Number(row.candidateCount ?? row.candidate_count ?? 0),
    error: get(row, "error") || undefined,
  };
}
function statusBadge(status: string) {
  if (["verified", "active", "ready", "valid"].includes(status))
    return <Badge tone="success">正常</Badge>;
  if (["failed", "invalid", "error"].includes(status))
    return <Badge tone="danger">异常</Badge>;
  return <Badge tone="warning">待验证</Badge>;
}
const orderStatusLabels: Record<string, string> = {
  pending_payment: "待支付",
  purchase_ready: "待确认购买",
  paid: "已支付",
  provisioning: "开通中",
  unknown: "结果待确认",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};
const onboardingStageLabels: Record<string, string> = {
  not_started: "尚未开始",
  cloudflare_zone: "Cloudflare Zone",
  registrar_nameservers: "域名服务器",
  cloudflare_dns: "DNS 与 HTTPS",
  baota_site: "宝塔站点",
  public_verification: "公网验证",
  completed: "已完成",
};
function domainStatus(row: DomainRow): EntityStatusMeta {
  if (!row.enabled) {
    return { label: "已停用", description: "域名已停用，不能分配给推广渠道。", tone: "neutral" };
  }
  if (row.lastError || [row.dnsStatus, row.sslStatus].some((value) => ["failed", "invalid", "error"].includes(value))) {
    return {
      label: "异常",
      description: row.lastError || "DNS 或 TLS 验证失败，请检查域名配置。",
      tone: "danger",
    };
  }
  if (row.channelSelectable) {
    return { label: "可用", description: "域名验证完成，可以分配给推广渠道。", tone: "success" };
  }
  return { label: "配置中", description: "域名仍在等待 DNS、TLS 或托管配置完成。", tone: "warning" };
}
function domainOrderStatus(row: DomainOrderRow): EntityStatusMeta {
  const label = orderStatusLabels[row.status] || row.status;
  const tone = row.status === "completed"
    ? "success"
    : row.status === "failed"
      ? "danger"
      : ["pending_payment", "purchase_ready", "paid", "provisioning", "unknown"].includes(row.status)
        ? "warning"
        : "neutral";
  return {
    label,
    description: row.failureReason || `当前域名订单状态为“${label}”。`,
    tone,
  };
}
const providerSourceLabels = {
  system_purchase: "系统购买",
  system_import: "系统接入",
  system_order: "系统订单",
  account_existing: "账户已有",
} as const;
function providerSourceTone(source: keyof typeof providerSourceLabels) {
  return source === "account_existing" ? "neutral" as const : "success" as const;
}
const cloudflareStatusMeta: Record<string, EntityStatusMeta> = {
  active: {
    label: "正常",
    description: "Cloudflare Zone 已激活。",
    tone: "success",
  },
  pending: {
    label: "待激活",
    description: "Cloudflare 正在等待域名服务器切换生效。",
    tone: "warning",
  },
  initializing: {
    label: "初始化中",
    description: "Cloudflare 正在初始化该 Zone。",
    tone: "warning",
  },
  moved: {
    label: "已迁移",
    description: "Cloudflare Zone 已迁移，当前不能直接接入系统。",
    tone: "danger",
  },
  deactivated: {
    label: "已停用",
    description: "Cloudflare Zone 已停用，当前不能接入系统。",
    tone: "danger",
  },
};
function cloudflareDomainStatus(row: CloudflareDomainRow): EntityStatusMeta {
  if (row.phishingDetected) {
    return {
      label: "风险",
      description: "Cloudflare 已将该 Zone 标记为疑似钓鱼，请核查后再接入系统。",
      tone: "danger",
    };
  }
  if (row.paused) {
    return { label: "已暂停", description: "Cloudflare Zone 当前处于暂停状态。", tone: "warning" };
  }
  return cloudflareStatusMeta[row.status] || {
    label: "未知状态",
    description: "Cloudflare 返回了未识别的 Zone 状态，当前按不可用处理。",
    tone: "danger",
  };
}
function integrationStatusBadge(connected: boolean) {
  return <Badge tone={connected ? "success" : "neutral"}>{connected ? "已接入" : "未接入"}</Badge>;
}
const currentSystemDomainMessage = "当前管理后台正在使用该域名或其子域名，不能作为落地页域名接入。";
function normalizeComparableHostname(value: string) {
  return value.trim().toLowerCase().replace(/\.$/, "");
}
function isCurrentSystemDomain(providerHostname: string, currentSystemHostname: string) {
  const providerDomain = normalizeComparableHostname(providerHostname);
  return currentSystemHostname !== ""
    && (currentSystemHostname === providerDomain
      || currentSystemHostname.endsWith(`.${providerDomain}`));
}
function CurrentSystemDomainWarning() {
  return (
    <Badge tone="danger" title={currentSystemDomainMessage}>
      当前系统域名
    </Badge>
  );
}
function nameSiloDomainStatus(row: NameSiloDomainRow): EntityStatusMeta {
  if (row.providerOwned) {
    return { label: "账户持有", description: "该域名当前存在于已配置的 NameSilo 账户中。", tone: "success" };
  }
  if (row.providerStatus === "failed") {
    return { label: "购买失败", description: row.order?.failureReason || "系统订单未完成购买。", tone: "danger" };
  }
  if (row.providerStatus === "cancelled") {
    return { label: "已取消", description: "系统订单已经取消，域名未进入 NameSilo 账户。", tone: "neutral" };
  }
  return {
    label: orderStatusLabels[row.providerStatus] || "尚未持有",
    description: "该域名尚未进入 NameSilo 账户。",
    tone: "warning",
  };
}
export function DomainsPage() {
  const { can, user } = useAuth();
  const canManage = can("promotion.domain.manage");
  const canPurchase = can("promotion.domain.purchase");
  const currentSystemHostname = typeof window === "undefined"
    ? ""
    : normalizeComparableHostname(window.location.hostname);
  const [rows, setRows] = useState<DomainRow[]>([]);
  const [cloudflareDomains, setCloudflareDomains] = useState<CloudflareDomainRow[]>([]);
  const [nameSiloDomains, setNameSiloDomains] = useState<NameSiloDomainRow[]>([]);
  const [externalErrors, setExternalErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [activeList, setActiveList] = useState<"system" | "cloudflare" | "namesilo">("system");
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [systemSource, setSystemSource] = useState("all");
  const [systemReady, setSystemReady] = useState("all");
  const [systemOnboarding, setSystemOnboarding] = useState("all");
  const [providerSource, setProviderSource] = useState("all");
  const [providerStatus, setProviderStatus] = useState("all");
  const [providerOnboarding, setProviderOnboarding] = useState("all");
  const [orderStatus, setOrderStatus] = useState("all");
  const [expiresBefore, setExpiresBefore] = useState("");
  const [systemSortBy, setSystemSortBy] = useState<SystemDomainSortBy>("id");
  const [systemSortOrder, setSystemSortOrder] = useState<ListSortOrder>("desc");
  const [cloudflareSortBy, setCloudflareSortBy] =
    useState<CloudflareDomainSortBy>("id");
  const [cloudflareSortOrder, setCloudflareSortOrder] =
    useState<ListSortOrder>("desc");
  const [nameSiloSortBy, setNameSiloSortBy] =
    useState<NameSiloDomainSortBy>("id");
  const [nameSiloSortOrder, setNameSiloSortOrder] =
    useState<ListSortOrder>("desc");
  const autoRefreshedList = useRef("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<DomainRow | null>(null);
  const [hostname, setHostname] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [pending, setPending] = useState(false);
  const [testing, setTesting] = useState("");
  const [onboardingPending, setOnboardingPending] = useState("");
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [purchaseLabel, setPurchaseLabel] = useState("");
  const [purchaseHostname, setPurchaseHostname] = useState("");
  const [purchaseYears, setPurchaseYears] = useState("1");
  const [resultKeyword, setResultKeyword] = useState("");
  const [domainSearch, setDomainSearch] = useState<DomainSearchState | null>(null);
  const [autoRenew, setAutoRenew] = useState(false);
  const [quote, setQuote] = useState<Record<string, unknown> | null>(null);
  const [order, setOrder] = useState<DomainOrderRow | null>(null);
  const [purchasePending, setPurchasePending] = useState(false);
  const [orderPending, setOrderPending] = useState("");
  const [importPending, setImportPending] = useState("");
  const [baotaPolicyOpen, setBaoTaPolicyOpen] = useState(false);
  const [baotaPolicy, setBaoTaPolicy] = useState<BaoTaDomainPolicy>(defaultBaoTaDomainPolicy);
  const [baotaCapability, setBaoTaCapability] = useState<BaoTaFirewallCapability>({ status: "unknown" });
  const [baotaPolicyLoading, setBaoTaPolicyLoading] = useState(false);
  const [baotaPolicySaving, setBaoTaPolicySaving] = useState(false);
  const [baotaPolicyError, setBaoTaPolicyError] = useState("");
  const load = useCallback(async (showLoading = true, refreshProvider = false) => {
    if (showLoading) setLoading(true);
    const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
    if (debouncedKeyword) query.set("keyword", debouncedKeyword);
    if (expiresBefore) query.set("expiresBefore", expiresBefore);
    if (activeList === "system") {
      if (systemSource !== "all") query.set("source", systemSource);
      if (systemReady !== "all") query.set("ready", systemReady);
      if (systemOnboarding !== "all") query.set("onboardingStatus", systemOnboarding);
      query.set("sortBy", systemSortBy);
      query.set("sortOrder", systemSortOrder);
    } else {
      if (providerSource !== "all") query.set("source", providerSource);
      if (providerStatus !== "all") query.set("providerStatus", providerStatus);
      if (providerOnboarding !== "all") query.set("onboardingStatus", providerOnboarding);
      if (activeList === "namesilo" && orderStatus !== "all") {
        query.set("orderStatus", orderStatus);
      }
      query.set(
        "sortBy",
        activeList === "cloudflare" ? cloudflareSortBy : nameSiloSortBy,
      );
      query.set(
        "sortOrder",
        activeList === "cloudflare" ? cloudflareSortOrder : nameSiloSortOrder,
      );
    }
    const endpoint = activeList === "system"
      ? `/api/domains?${query}`
      : activeList === "cloudflare"
        ? `/api/domains/cloudflare${refreshProvider ? "/refresh" : ""}?${query}`
        : `/api/domains/namesilo${refreshProvider ? "/sync" : ""}?${query}`;
    try {
      const payload = await apiRequest(endpoint, {
        method: activeList !== "system" && refreshProvider ? "POST" : "GET",
      });
      const list = unwrapList<unknown>(payload);
      setTotal(list.total);
      setExternalErrors((current) => ({ ...current, [activeList]: "" }));
      if (activeList === "system") setRows(list.rows.map(normalize));
      else if (activeList === "cloudflare") {
        setCloudflareDomains(list.rows.map(normalizeCloudflareDomain));
      } else {
        setNameSiloDomains(list.rows.map(normalizeNameSiloDomain));
        const recovered = (payload as { data?: { recoveredDomains?: unknown[] } }).data?.recoveredDomains;
        if (Array.isArray(recovered) && recovered.length) {
          toast.success(`${recovered.length} 个 NameSilo 异常订单已自动确认并开始接入`);
        }
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : `${activeList} 域名读取失败`;
      setExternalErrors((current) => ({ ...current, [activeList]: message }));
      if (!refreshProvider) {
        setTotal(0);
        if (activeList === "system") setRows([]);
        else if (activeList === "cloudflare") setCloudflareDomains([]);
        else setNameSiloDomains([]);
      } else {
        toast.error(`刷新失败，继续显示上次缓存：${message}`);
      }
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [activeList, cloudflareSortBy, cloudflareSortOrder, debouncedKeyword, expiresBefore, nameSiloSortBy, nameSiloSortOrder, orderStatus, page, pageSize, providerOnboarding, providerSource, providerStatus, systemOnboarding, systemReady, systemSortBy, systemSortOrder, systemSource]);
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      await load();
      if (
        !cancelled &&
        activeList !== "system" &&
        autoRefreshedList.current !== activeList
      ) {
        autoRefreshedList.current = activeList;
        await load(false, true);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [load]);
  useEffect(() => {
    if (activeList === "system") autoRefreshedList.current = "";
  }, [activeList]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [keyword]);
  const hasActiveOnboarding = rows.some((row) =>
    ["idle", "running", "waiting"].includes(row.onboarding.status)
  );
  useEffect(() => {
    if (activeList !== "system" || !hasActiveOnboarding) return;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await load(false);
      } catch {
        // Keep the previous rows and retry on the next interval.
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [activeList, hasActiveOnboarding, load]);
  const visibleDomainOptions = useMemo(() => {
    const search = resultKeyword.trim().toLowerCase();
    return (domainSearch?.options || []).filter((option) =>
      !search || option.domain.toLowerCase().includes(search),
    );
  }, [domainSearch, resultKeyword]);
  useEffect(() => {
    const searchId = domainSearch?.searchId;
    if (!purchaseOpen || domainSearch?.status !== "running" || !searchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const payload = await apiRequest(`/api/domain-orders/search/${searchId}`);
        if (cancelled) return;
        const value = (payload as { data?: { search?: unknown } }).data?.search;
        const next = normalizeSearch(value);
        setDomainSearch(next);
        if (next.status === "failed") {
          toast.error(next.error || "域名后缀查询失败");
        } else if (next.status === "running") {
          timer = setTimeout(() => void poll(), 1000);
        }
      } catch (caught) {
        if (cancelled) return;
        setDomainSearch((current) => current ? { ...current, status: "failed" } : current);
        toast.error(caught instanceof Error ? caught.message : "域名查询状态读取失败");
      }
    };
    timer = setTimeout(() => void poll(), 500);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [domainSearch?.searchId, domainSearch?.status, purchaseOpen]);

  async function openBaoTaPolicy() {
    setBaoTaPolicyOpen(true);
    setBaoTaPolicyLoading(true);
    setBaoTaPolicyError("");
    try {
      const payload = await apiRequest("/api/system/configuration");
      const platforms = (payload as { data?: { platforms?: unknown[] } }).data?.platforms || [];
      let platform = platforms.find((value) =>
        String((value as Record<string, unknown>).key || "") === "baota"
      );
      if (!platform) throw new Error("未找到宝塔系统配置");
      const current = baoTaSettings(platform);
      if (current.configured && current.enabled) {
        const tested = await apiRequest("/api/system/configuration/baota/test", {
          method: "POST",
        }) as { data?: { ok?: boolean; message?: string; platform?: unknown } };
        platform = tested.data?.platform || platform;
        if (!tested.data?.ok) {
          setBaoTaPolicyError(tested.data?.message || "宝塔连接或插件检测失败");
        }
      }
      const next = baoTaSettings(platform);
      setBaoTaPolicy(next.policy);
      setBaoTaCapability(next.capability);
      if (!next.configured || !next.enabled) {
        setBaoTaPolicyError("请先在系统配置中启用并测试宝塔面板");
      }
    } catch (caught) {
      setBaoTaPolicyError(caught instanceof Error ? caught.message : "宝塔策略读取失败");
      setBaoTaCapability({ status: "unknown" });
    } finally {
      setBaoTaPolicyLoading(false);
    }
  }

  async function saveBaoTaPolicy() {
    if (baotaCapability.status !== "available") return;
    setBaoTaPolicySaving(true);
    try {
      const payload = await apiRequest("/api/system/configuration/baota", {
        method: "PUT",
        body: JSON.stringify({
          firewallCdnEnabled: baotaPolicy.cdnEnabled,
          firewallCcEnabled: baotaPolicy.ccEnabled,
          firewallChinaBlocked: baotaPolicy.chinaBlocked,
        }),
      });
      const platform = (payload as { data?: { platform?: unknown } }).data?.platform;
      if (platform) {
        const next = baoTaSettings(platform);
        setBaoTaPolicy(next.policy);
        setBaoTaCapability(next.capability);
      }
      setBaoTaPolicyOpen(false);
      toast.success("宝塔策略已保存，将应用到后续域名接入");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "宝塔策略保存失败");
    } finally {
      setBaoTaPolicySaving(false);
    }
  }

  function open(row: DomainRow) {
    setEditing(row);
    setHostname(row.hostname);
    setEnabled(row.enabled);
    setDrawer(true);
  }
  async function continueOnboarding(row: DomainRow, quiet = false) {
    if (!row.id) return null;
    setOnboardingPending(row.id);
    try {
      const payload = await apiRequest(`/api/domains/${row.id}/onboarding/continue`, {
        method: "POST",
      });
      const value = (payload as { data?: { domain?: unknown } }).data?.domain;
      const updated = value ? normalize(value) : row;
      setEditing((current) => current?.id === row.id ? updated : current);
      await load();
      if (!quiet) {
        if (updated.onboarding.status === "completed") {
          toast.success("域名已完成自动接入并通过验证");
        } else if (updated.onboarding.status === "failed") {
          toast.error(updated.onboarding.message || "自动接入未完成");
        } else {
          toast.success(updated.onboarding.message || "接入状态已更新");
        }
      }
      return updated;
    } catch (caught) {
      if (!quiet) toast.error(caught instanceof Error ? caught.message : "自动接入失败");
      return null;
    } finally {
      setOnboardingPending("");
    }
  }
  async function save() {
    if (!editing || !hostname.trim()) return;
    setPending(true);
    try {
      const payload = await apiRequest(`/api/domains/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      });
      const saved = (payload as { data?: { domain?: unknown } }).data?.domain;
      const savedRow = saved ? normalize(saved) : null;
      if (savedRow) setEditing(savedRow);
      setDrawer(false);
      await load();
      toast.success("域名已更新");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }
  async function requestDomainSearch() {
    if (!purchaseLabel.trim()) return;
    setPurchasePending(true);
    setPurchaseHostname("");
    setQuote(null);
    setOrder(null);
    setResultKeyword("");
    try {
      const payload = await apiRequest("/api/domain-orders/search", {
        method: "POST",
        body: JSON.stringify({
          label: purchaseLabel.trim().toLowerCase(),
          years: Number(purchaseYears),
        }),
      });
      const value = (payload as { data?: { search?: unknown } }).data?.search;
      const next = normalizeSearch(value);
      setDomainSearch(next);
      if (next.status === "failed") {
        toast.error(next.error || "域名后缀查询失败");
      } else if (next.status === "completed" && !next.options.length) {
        toast.error("没有找到可购买的域名后缀");
      }
    } catch (caught) {
      setDomainSearch(null);
      toast.error(caught instanceof Error ? caught.message : "域名后缀查询失败");
    } finally {
      setPurchasePending(false);
    }
  }
  async function requestQuote() {
    if (!purchaseHostname.trim()) return;
    setPurchasePending(true);
    try {
      const payload = await apiRequest("/api/domain-orders/quote", {
        method: "POST",
        body: JSON.stringify({
          hostname: purchaseHostname.trim().toLowerCase(),
          years: Number(purchaseYears),
        }),
      });
      setQuote((payload as { data?: { quote?: Record<string, unknown> } }).data?.quote || null);
      setOrder(null);
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "域名询价失败");
    } finally {
      setPurchasePending(false);
    }
  }
  async function createOrder() {
    const quoteId = String(quote?.quoteId || quote?.id || "");
    if (!quoteId) return;
    setPurchasePending(true);
    try {
      const payload = await apiRequest("/api/domain-orders", {
        method: "POST",
        body: JSON.stringify({ quoteId, autoRenew }),
      });
      const created = (payload as { data?: { order?: unknown } }).data?.order;
      setOrder(created ? normalizeOrder(created) : null);
      setQuote(null);
      await load();
      toast.success("域名订单已创建");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "订单创建失败");
    } finally {
      setPurchasePending(false);
    }
  }
  async function verify(row: DomainRow) {
    if (!row.id) return;
    setTesting(row.id);
    try {
      const payload = await apiRequest(`/api/domains/${row.id}/verify`, { method: "POST" });
      const value = (payload as { data?: { domain?: unknown } }).data?.domain;
      const updated = value ? normalize(value) : null;
      if (updated && editing?.id === row.id) setEditing(updated);
      await load();
      if (updated?.channelSelectable) toast.success("域名验证已完成，可用于推广渠道");
      else toast.error(updated?.lastError || "DNS 或 TLS 尚未验证通过，请检查解析记录");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "验证失败");
    } finally {
      setTesting("");
    }
  }
  async function runOrderAction(row: DomainOrderRow, action: "mock-payment" | "provision" | "cancel") {
    if (!row.id) return;
    if (action === "provision" && row.provider === "namesilo" && !(await confirmAction({
      title: `确认通过 NameSilo 购买 ${row.hostname}？`,
      description: `系统会先核对 NameSilo 账户是否已经持有该域名；只有确认未持有时，才会按系统配置的支付方式提交 ${row.years} 年购买请求，预计金额 ${row.currency} ${row.amount.toFixed(2)}。`,
      confirmText: "确认购买",
    }))) return;
    if (action === "cancel" && !(await confirmAction({
      title: `取消域名订单 ${row.hostname}？`,
      description: "取消后需要重新询价才能再次购买。",
      confirmText: "确认取消",
    }))) return;
    setOrderPending(`${row.id}:${action}`);
    try {
      let payload = await apiRequest(`/api/domain-orders/${row.id}/${action}`, { method: "POST" });
      let nextValue = (payload as { data?: { order?: unknown } }).data?.order;
      let provisionedDomain = (payload as { data?: { domain?: unknown } }).data?.domain;
      let updated = nextValue ? normalizeOrder(nextValue) : row;
      if (action === "mock-payment" && updated.allowedActions.provision) {
        payload = await apiRequest(`/api/domain-orders/${row.id}/provision`, { method: "POST" });
        nextValue = (payload as { data?: { order?: unknown } }).data?.order;
        provisionedDomain = (payload as { data?: { domain?: unknown } }).data?.domain;
        updated = nextValue ? normalizeOrder(nextValue) : updated;
      }
      if (order?.id === row.id) setOrder(updated);
      await load();
      toast.success(
        action === "cancel"
          ? "订单已取消"
          : updated.status === "completed"
            ? "域名已开通，正在启动自动接入"
            : updated.status === "unknown"
              ? "注册结果待确认，刷新 NameSilo 域名列表后系统会自动同步"
              : "订单状态已更新",
      );
      if (updated.status === "completed" && provisionedDomain) {
        await continueOnboarding(normalize(provisionedDomain));
      }
    } catch (caught) {
      await load().catch(() => undefined);
      toast.error(caught instanceof Error ? caught.message : "订单操作失败");
    } finally {
      setOrderPending("");
    }
  }
  async function importProviderDomain(
    provider: "cloudflare" | "namesilo",
    hostnameValue: string,
    directPurchase = false,
  ) {
    const nameSiloFlow = provider === "namesilo";
    if (!(await confirmAction({
      title: `接入域名 ${hostnameValue}？`,
      description: nameSiloFlow
        ? `${directPurchase ? "" : "该域名不是由本系统直接购买。"}系统会先将 NameSilo 域名服务器切换到当前 Cloudflare 账户，再整理 Cloudflare 中根域名的 A、AAAA、CNAME 和验证记录。旧 DNS 服务商中的 MX、其他 TXT、子域名等记录不会自动迁移，切换后可能失效；请先备份并迁移需要保留的解析。`
        : `${directPurchase ? "" : "该域名不是由本系统直接购买。"}系统会接管当前 Cloudflare Zone 中用于落地页的根域名解析，删除冲突的 A、AAAA、CNAME 记录并重建路由和验证记录。MX、其他 TXT 及其他子域名记录不会删除，请仍先备份现有解析。`,
      confirmText: "确认接入",
      destructive: true,
    }))) return;
    const pendingKey = `${provider}:${hostnameValue}`;
    setImportPending(pendingKey);
    try {
      const payload = await apiRequest("/api/domains/provider-import", {
        method: "POST",
        body: JSON.stringify({
          provider,
          hostname: hostnameValue,
          confirmDnsReplace: true,
        }),
      });
      const saved = (payload as { data?: { domain?: unknown } }).data?.domain;
      const savedRow = saved ? normalize(saved) : null;
      await load();
      if (!savedRow) {
        toast.error("域名接入记录创建失败");
        return;
      }
      toast.success("域名接入记录已创建，正在执行自动接入");
      await continueOnboarding(savedRow);
    } catch (caught) {
      await load().catch(() => undefined);
      toast.error(caught instanceof Error ? caught.message : "域名接入失败");
    } finally {
      setImportPending("");
    }
  }
  async function deleteOrder(row: DomainOrderRow) {
    if (!row.id || !(await confirmAction({
      title: `删除订单记录 ${row.hostname}？`,
      description: "只删除本系统中的失败或已取消订单记录，不会删除 NameSilo 账户中的域名，也不会发起退款。",
      confirmText: "确认删除",
      destructive: true,
    }))) return;
    setOrderPending(`${row.id}:delete`);
    try {
      await apiRequest(`/api/domain-orders/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("订单记录已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "订单删除失败");
    } finally {
      setOrderPending("");
    }
  }
  async function remove(row: DomainRow) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `删除域名 ${row.hostname}？`,
        description: "只删除本系统记录，不会删除 NameSilo 注册、Cloudflare Zone、DNS 或宝塔站点；仍被渠道或集成使用时不能删除。",
        confirmText: "确认删除",
        destructive: true,
      }))
    )
      return;
    try {
      await apiRequest(`/api/domains/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("域名已删除");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "删除失败");
    }
  }
  function changeSystemSort(nextSortBy: SystemDomainSortBy, nextSortOrder: ListSortOrder) {
    setSystemSortBy(nextSortBy);
    setSystemSortOrder(nextSortOrder);
    setPage(1);
  }
  function changeCloudflareSort(nextSortBy: CloudflareDomainSortBy, nextSortOrder: ListSortOrder) {
    setCloudflareSortBy(nextSortBy);
    setCloudflareSortOrder(nextSortOrder);
    setPage(1);
  }
  function changeNameSiloSort(nextSortBy: NameSiloDomainSortBy, nextSortOrder: ListSortOrder) {
    setNameSiloSortBy(nextSortBy);
    setNameSiloSortOrder(nextSortOrder);
    setPage(1);
  }
  const waitingForDomainSearch = !purchaseHostname
    && domainSearch?.status === "running";
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: activeList === "system"
            ? "搜索系统域名"
            : activeList === "cloudflare"
              ? "搜索 Cloudflare 域名"
              : "搜索 NameSilo 域名",
        }}
        filters={
          <>
            <div className="flex items-center gap-2">
              <Button
                variant={activeList === "system" ? "secondary" : "outline"}
                aria-pressed={activeList === "system"}
                onClick={() => {
                  setActiveList("system");
                  setKeyword("");
                  setPage(1);
                }}
              >
                系统域名
              </Button>
              <Button
                variant={activeList === "cloudflare" ? "secondary" : "outline"}
                aria-pressed={activeList === "cloudflare"}
                onClick={() => {
                  setActiveList("cloudflare");
                  setKeyword("");
                  setPage(1);
                }}
              >
                Cloudflare 域名
              </Button>
              <Button
                variant={activeList === "namesilo" ? "secondary" : "outline"}
                aria-pressed={activeList === "namesilo"}
                onClick={() => {
                  setActiveList("namesilo");
                  setKeyword("");
                  setPage(1);
                }}
              >
                NameSilo 域名
              </Button>
            </div>
            {activeList === "system" ? (
              <>
                <SelectField
                  value={systemSource}
                  onValueChange={(value) => { setSystemSource(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部来源" },
                    { value: "purchased", label: "平台购买" },
                    { value: "connected", label: "外部接入" },
                  ]}
                />
                <SelectField
                  value={systemReady}
                  onValueChange={(value) => { setSystemReady(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部就绪状态" },
                    { value: "true", label: "可用于渠道" },
                    { value: "false", label: "配置中" },
                  ]}
                />
                <SelectField
                  value={systemOnboarding}
                  onValueChange={(value) => { setSystemOnboarding(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部接入状态" },
                    { value: "idle", label: "未开始" },
                    { value: "running", label: "进行中" },
                    { value: "waiting", label: "等待中" },
                    { value: "failed", label: "失败" },
                    { value: "completed", label: "已完成" },
                  ]}
                />
              </>
            ) : (
              <>
                <SelectField
                  value={providerSource}
                  onValueChange={(value) => { setProviderSource(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部来源" },
                    { value: "system_purchase", label: "系统购买" },
                    ...(activeList === "cloudflare"
                      ? [{ value: "system_import", label: "系统接入" }]
                      : [{ value: "system_order", label: "系统订单" }]),
                    { value: "account_existing", label: "账户已有" },
                  ]}
                />
                <SelectField
                  value={providerStatus}
                  onValueChange={(value) => { setProviderStatus(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部服务商状态" },
                    { value: "active", label: "正常" },
                    { value: "pending", label: "待生效" },
                    { value: "deactivated", label: "已停用" },
                    { value: "failed", label: "失败" },
                  ]}
                />
                {activeList === "namesilo" ? (
                  <SelectField
                    value={orderStatus}
                    onValueChange={(value) => { setOrderStatus(value); setPage(1); }}
                    options={[
                      { value: "all", label: "全部订单状态" },
                      { value: "pending_payment", label: "待支付" },
                      { value: "purchase_ready", label: "待购买" },
                      { value: "provisioning", label: "购买中" },
                      { value: "unknown", label: "待确认" },
                      { value: "completed", label: "已完成" },
                      { value: "failed", label: "失败" },
                      { value: "cancelled", label: "已取消" },
                    ]}
                  />
                ) : null}
                <SelectField
                  value={providerOnboarding}
                  onValueChange={(value) => { setProviderOnboarding(value); setPage(1); }}
                  options={[
                    { value: "all", label: "全部接入状态" },
                    { value: "connected", label: "已接入" },
                    { value: "not_connected", label: "未接入" },
                  ]}
                />
              </>
            )}
            {activeList !== "cloudflare" ? (
              <DatePickerField
                ariaLabel="到期不晚于"
                value={expiresBefore}
                onValueChange={(value) => { setExpiresBefore(value); setPage(1); }}
                placeholder="到期不晚于"
                className="w-[148px]"
              />
            ) : null}
          </>
        }
        meta={`${total} 个域名`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load(true, activeList !== "system")}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {user?.isAdmin ? (
              <Button variant="outline" onClick={() => void openBaoTaPolicy()}>
                <ShieldCheckIcon size={17} />
                宝塔策略
              </Button>
            ) : null}
            {canPurchase ? (
              <Button onClick={() => {
                setPurchaseLabel("");
                setPurchaseHostname("");
                setPurchaseYears("1");
                setResultKeyword("");
                setDomainSearch(null);
                setAutoRenew(false);
                setQuote(null);
                setOrder(null);
                setPurchaseOpen(true);
              }}>
                <ShoppingCartIcon size={17} />
                购买域名
              </Button>
            ) : null}
          </>
        }
      />
      <ListPagination
        ariaLabel={`${activeList} 域名分页`}
        page={page}
        pageSize={pageSize}
        total={total}
        disabled={loading}
        onPageChange={setPage}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      />
      {activeList === "system" ? (
        <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : rows.length ? (
          <div className="table-scroll">
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <ListSortableHead sortKey="id" activeSortKey={systemSortBy} sortOrder={systemSortOrder} defaultOrder="desc" onSort={changeSystemSort} adaptive>域名</ListSortableHead>
                  <ListSortableHead sortKey="source" activeSortKey={systemSortBy} sortOrder={systemSortOrder} onSort={changeSystemSort}>来源</ListSortableHead>
                  <TableHead>托管</TableHead>
                  <TableHead>DNS / TLS</TableHead>
                  <ListSortableHead sortKey="ready" activeSortKey={systemSortBy} sortOrder={systemSortOrder} onSort={changeSystemSort}>就绪状态</ListSortableHead>
                  <ListSortableHead sortKey="expiresAt" activeSortKey={systemSortBy} sortOrder={systemSortOrder} onSort={changeSystemSort}>到期时间</ListSortableHead>
                  <TableHead>绑定渠道</TableHead>
                  <ListSortableHead sortKey="lastVerifiedAt" activeSortKey={systemSortBy} sortOrder={systemSortOrder} defaultOrder="desc" onSort={changeSystemSort}>最近验证</ListSortableHead>
                  <ListSortableHead sortKey="onboardingStatus" activeSortKey={systemSortBy} sortOrder={systemSortOrder} onSort={changeSystemSort}>接入状态</ListSortableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.readKey}>
                    <TableCell>
                      <EntityPrimaryCell
                        title={row.hostname}
                        id={row.id}
                        status={{
                          ...domainStatus(row),
                          details: [
                            { label: "DNS", value: row.dnsStatus },
                            { label: "TLS", value: row.sslStatus },
                            { label: "绑定渠道", value: row.boundCount },
                          ],
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <Badge
                        tone={row.acquisitionType === "purchased" ? "success" : "neutral"}
                        title={
                          row.acquisitionType === "purchased"
                            ? "域名通过平台购买并纳入系统管理。"
                            : "域名由外部注册商接入系统。"
                        }
                      >
                        {row.acquisitionType === "purchased" ? "平台购买" : "外部接入"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        tone="neutral"
                        title={
                          row.managementMode === "platform"
                            ? "系统可通过已配置的 NameSilo、Cloudflare 凭据自动切换域名服务器并配置解析。"
                            : "注册商侧由用户自行管理；接入完成后，系统仍会配置 Cloudflare DNS、TLS 和站点。"
                        }
                      >
                        {row.managementMode === "platform" ? "平台托管" : "自行管理"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1 whitespace-nowrap">
                        <span className="justify-self-end">{statusBadge(row.dnsStatus)}</span>
                        <span className="text-muted-foreground">/</span>
                        <span className="justify-self-start">{statusBadge(row.sslStatus)}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge tone={row.channelSelectable ? "success" : "warning"}>
                        {row.channelSelectable ? "可用于渠道" : "配置中"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDateTime(row.expiresAt)}</TableCell>
                    <TableCell>{row.boundCount}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(row.lastVerifiedAt)}
                    </TableCell>
                    <TableCell>{integrationStatusBadge(true)}</TableCell>
                    <TableCell>
                      <div className="flex min-w-max items-center justify-end gap-2">
                        {canManage ? (
                          <>
                            {row.onboarding.canContinue ? (
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={!row.id || onboardingPending === row.id}
                                onClick={() => void continueOnboarding(row)}
                              >
                                {onboardingPending === row.id ? <Spinner /> : null}
                                立即重试
                              </Button>
                            ) : null}
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={!row.id || testing === row.id}
                              onClick={() => void verify(row)}
                            >
                              {testing === row.id ? <Spinner /> : null}
                              立即验证
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={!row.id}
                              onClick={() => open(row)}
                            >
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
            title="还没有域名"
            description={externalErrors.system || "添加推广域名并完成 DNS、SSL 验证。"}
          />
        )}
        </ListTableCard>
      ) : activeList === "cloudflare" ? (
        <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner /></div>
        ) : cloudflareDomains.length ? (
          <div className="table-scroll">
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <ListSortableHead sortKey="id" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} defaultOrder="desc" onSort={changeCloudflareSort} adaptive>域名</ListSortableHead>
                  <ListSortableHead sortKey="source" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} onSort={changeCloudflareSort}>来源</ListSortableHead>
                  <ListSortableHead sortKey="providerStatus" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} onSort={changeCloudflareSort}>Cloudflare 状态</ListSortableHead>
                  <ListSortableHead sortKey="onboardingStatus" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} onSort={changeCloudflareSort}>接入状态</ListSortableHead>
                  <ListSortableHead sortKey="createdAt" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} defaultOrder="desc" onSort={changeCloudflareSort}>创建时间</ListSortableHead>
                  <ListSortableHead sortKey="updatedAt" activeSortKey={cloudflareSortBy} sortOrder={cloudflareSortOrder} defaultOrder="desc" onSort={changeCloudflareSort}>更新时间</ListSortableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cloudflareDomains.map((row) => {
                  const currentSystemDomain = isCurrentSystemDomain(
                    row.hostname,
                    currentSystemHostname,
                  );
                  return (
                    <TableRow key={row.readKey}>
                      <TableCell>
                        <EntityPrimaryCell
                          title={row.hostname}
                          id={row.id}
                          status={cloudflareDomainStatus(row)}
                        />
                      </TableCell>
                      <TableCell>
                        <Badge tone={providerSourceTone(row.source)}>
                          {providerSourceLabels[row.source]}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge tone={cloudflareDomainStatus(row).tone}>
                          {cloudflareDomainStatus(row).label}
                        </Badge>
                      </TableCell>
                      <TableCell>{integrationStatusBadge(Boolean(row.systemDomainId))}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.updatedAt)}</TableCell>
                      <TableCell>
                        <div className="flex min-w-max items-center justify-end gap-2">
                          {currentSystemDomain ? <CurrentSystemDomainWarning /> : null}
                          {!row.systemDomainId && canManage ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={currentSystemDomain || importPending === `cloudflare:${row.hostname}`}
                              title={currentSystemDomain ? currentSystemDomainMessage : undefined}
                              onClick={() => void importProviderDomain("cloudflare", row.hostname)}
                            >
                              {importPending === `cloudflare:${row.hostname}` ? <Spinner /> : null}
                              接入系统
                            </Button>
                          ) : !currentSystemDomain ? (
                            <span className="text-muted-foreground">-</span>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title={externalErrors.cloudflare ? "Cloudflare 域名读取失败" : "暂无 Cloudflare 域名"}
            description={externalErrors.cloudflare || "当前 Cloudflare 账户下没有可见的 Zone。"}
          />
        )}
        </ListTableCard>
      ) : (
        <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner /></div>
        ) : nameSiloDomains.length ? (
          <div className="table-scroll">
            <Table layout="list">
              <TableHeader>
                <TableRow>
                  <ListSortableHead sortKey="id" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} defaultOrder="desc" onSort={changeNameSiloSort} adaptive>域名</ListSortableHead>
                  <ListSortableHead sortKey="source" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} onSort={changeNameSiloSort}>来源</ListSortableHead>
                  <ListSortableHead sortKey="providerStatus" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} onSort={changeNameSiloSort}>NameSilo 状态</ListSortableHead>
                  <ListSortableHead sortKey="createdAt" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} defaultOrder="desc" onSort={changeNameSiloSort}>创建时间</ListSortableHead>
                  <ListSortableHead sortKey="updatedAt" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} defaultOrder="desc" onSort={changeNameSiloSort}>更新时间</ListSortableHead>
                  <ListSortableHead sortKey="expiresAt" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} onSort={changeNameSiloSort}>到期时间</ListSortableHead>
                  <ListSortableHead sortKey="orderStatus" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} onSort={changeNameSiloSort}>系统订单</ListSortableHead>
                  <ListSortableHead sortKey="onboardingStatus" activeSortKey={nameSiloSortBy} sortOrder={nameSiloSortOrder} onSort={changeNameSiloSort}>接入状态</ListSortableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {nameSiloDomains.map((row) => {
                  const itemOrder = row.order;
                  const busy = Boolean(itemOrder?.id)
                    && orderPending.startsWith(`${itemOrder?.id}:`);
                  const showsOrderActions = canPurchase && Boolean(itemOrder && (
                    itemOrder.allowedActions.mockPayment
                    || (itemOrder.allowedActions.provision && !row.providerOwned)
                    || itemOrder.allowedActions.cancel
                    || (itemOrder.allowedActions.delete && !row.providerOwned)
                  ));
                  const showsImport = row.providerOwned
                    && !row.systemDomainId
                    && canManage
                    && !itemOrder;
                  const currentSystemDomain = isCurrentSystemDomain(
                    row.hostname,
                    currentSystemHostname,
                  );
                  return (
                    <TableRow key={row.readKey}>
                      <TableCell>
                        <EntityPrimaryCell
                          title={row.hostname}
                          id={row.id}
                          status={nameSiloDomainStatus(row)}
                          description={itemOrder?.failureReason ? (
                            <span className="text-destructive">{itemOrder.failureReason}</span>
                          ) : undefined}
                        />
                      </TableCell>
                      <TableCell>
                        <Badge tone={providerSourceTone(row.source)}>
                          {providerSourceLabels[row.source]}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge tone={nameSiloDomainStatus(row).tone}>
                          {nameSiloDomainStatus(row).label}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.updatedAt)}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.expiresAt)}</TableCell>
                      <TableCell>
                        {itemOrder ? (
                          <div className="cell-main">
                            <Badge tone={domainOrderStatus(itemOrder).tone}>
                              {orderStatusLabels[itemOrder.status] || itemOrder.status}
                            </Badge>
                            <span>{itemOrder.years} 年 · {itemOrder.currency} {itemOrder.amount.toFixed(2)}</span>
                            <span>{formatDateTime(itemOrder.createdAt)}</span>
                          </div>
                        ) : <span className="text-muted-foreground">-</span>}
                      </TableCell>
                      <TableCell>{integrationStatusBadge(Boolean(row.systemDomainId))}</TableCell>
                      <TableCell>
                        <div className="flex min-w-max items-center justify-end gap-2">
                          {currentSystemDomain ? <CurrentSystemDomainWarning /> : null}
                          {canPurchase && itemOrder?.allowedActions.mockPayment ? (
                            <Button size="sm" disabled={!itemOrder.id || busy} onClick={() => void runOrderAction(itemOrder, "mock-payment")}>
                              {busy ? <Spinner /> : null}确认支付并开通
                            </Button>
                          ) : null}
                          {canPurchase && itemOrder?.allowedActions.provision && !row.providerOwned ? (
                            <Button size="sm" disabled={!itemOrder.id || busy} onClick={() => void runOrderAction(itemOrder, "provision")}>
                              {busy ? <Spinner /> : null}{itemOrder.status === "failed" ? "重试购买" : "确认购买"}
                            </Button>
                          ) : null}
                          {canPurchase && itemOrder?.allowedActions.cancel ? (
                            <Button size="sm" variant="outline" className="text-destructive" disabled={!itemOrder.id || busy} onClick={() => void runOrderAction(itemOrder, "cancel")}>
                              取消
                            </Button>
                          ) : null}
                          {canPurchase && itemOrder?.allowedActions.delete && !row.providerOwned ? (
                            <Button
                              variant="destructive"
                              size="sm"
                              disabled={!itemOrder.id || busy}
                              onClick={() => void deleteOrder(itemOrder)}
                            >
                              删除订单
                            </Button>
                          ) : null}
                          {showsImport ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={currentSystemDomain || importPending === `namesilo:${row.hostname}`}
                              title={currentSystemDomain ? currentSystemDomainMessage : undefined}
                              onClick={() => void importProviderDomain(
                                "namesilo",
                                row.hostname,
                                row.source === "system_purchase",
                              )}
                            >
                              {importPending === `namesilo:${row.hostname}` ? <Spinner /> : null}
                              接入系统
                            </Button>
                          ) : null}
                          {!showsOrderActions && !showsImport && !currentSystemDomain ? (
                            <span className="text-muted-foreground">-</span>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title={externalErrors.namesilo ? "NameSilo 域名读取失败" : "暂无 NameSilo 域名"}
            description={externalErrors.namesilo || "当前 NameSilo 账户下没有域名。"}
          />
        )}
        </ListTableCard>
      )}
      <Modal
        open={baotaPolicyOpen}
        onClose={() => !baotaPolicySaving && setBaoTaPolicyOpen(false)}
        title="宝塔策略"
        description="策略会应用到之后的自动域名接入；未安装 Nginx 防火墙插件时系统会自动跳过。"
        footer={
          <>
            <Button variant="outline" onClick={() => setBaoTaPolicyOpen(false)}>
              关闭
            </Button>
            <Button
              disabled={baotaPolicyLoading || baotaPolicySaving || baotaCapability.status !== "available"}
              onClick={() => void saveBaoTaPolicy()}
            >
              {baotaPolicySaving ? <Spinner /> : null}
              保存策略
            </Button>
          </>
        }
      >
        {baotaPolicyLoading ? (
          <div className="loading-state min-h-32">
            <Spinner />
            正在检测宝塔和防火墙插件…
          </div>
        ) : (
          <div className="grid gap-4">
            <section className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={baotaCapability.status === "available" ? "success" : "neutral"}>
                  {baotaCapability.status === "available"
                    ? "防火墙插件可用"
                    : baotaCapability.status === "unavailable"
                      ? "未检测到防火墙插件"
                      : "插件状态未知"}
                </Badge>
                {baotaCapability.checkedAt ? (
                  <span className="text-sm text-muted-foreground">
                    检测于 {formatDateTime(baotaCapability.checkedAt)}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {baotaCapability.status === "available"
                  ? "以下策略将在宝塔站点和反向代理创建后应用。"
                  : "域名仍会正常完成站点、反向代理和公网验证，防火墙配置不会阻断接入。"}
              </p>
              {baotaPolicyError ? (
                <p className="mt-2 text-sm leading-6 text-destructive">{baotaPolicyError}</p>
              ) : null}
            </section>
            <div className="grid gap-3">
              {[
                {
                  key: "cdnEnabled" as const,
                  label: "CDN 模式",
                  description: "让宝塔防火墙按 CDN 回源场景处理访客地址。",
                },
                {
                  key: "ccEnabled" as const,
                  label: "CC 防御",
                  description: "控制宝塔防火墙插件的站点 CC 防御开关。",
                },
                {
                  key: "chinaBlocked" as const,
                  label: "中国地区拦截",
                  description: "开启后由宝塔防火墙插件拦截中国地区访问。",
                },
              ].map((setting) => (
                <div
                  key={setting.key}
                  className="flex items-center justify-between gap-4 rounded-lg border border-border px-3 py-3"
                >
                  <div>
                    <div className="text-sm font-medium">{setting.label}</div>
                    <p className="mt-1 text-sm leading-5 text-muted-foreground">
                      {setting.description}
                    </p>
                  </div>
                  <Switch
                    checked={baotaPolicy[setting.key]}
                    disabled={baotaCapability.status !== "available" || baotaPolicySaving}
                    onCheckedChange={(checked) =>
                      setBaoTaPolicy((current) => ({ ...current, [setting.key]: checked }))
                    }
                    aria-label={setting.label}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
      <Drawer
        open={drawer}
        onClose={() => !pending && !onboardingPending && setDrawer(false)}
        title="域名接入与验证"
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={pending || !hostname.trim()}
              onClick={() => void save()}
            >
              {pending ? <Spinner /> : null}保存设置
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <DrawerFormLayout>
            <DrawerFormSection title="基础信息" hideHeader>
              <DrawerFormField label="域名" required>
                <Input
                  value={hostname}
                  disabled={Boolean(editing)}
                  onChange={(e) => setHostname(e.target.value)}
                  placeholder="example.com"
                />
              </DrawerFormField>
              <DrawerFormField
                label="启用域名"
                hint="停用后不会分配给新的推广渠道。"
              >
                <div className="flex h-8 items-center gap-3">
                  <Switch checked={enabled} onCheckedChange={setEnabled} />
                  <span className="text-sm">{enabled ? "启用" : "停用"}</span>
                </div>
              </DrawerFormField>
            </DrawerFormSection>
            {editing ? (
              <DrawerFormSection
                title="自动接入"
                description="系统会在后台依次核对 Cloudflare Zone、域名服务器、DNS、宝塔站点和公网可用性，无需反复点击继续。"
              >
                <DrawerFormField label="当前状态">
                  <div className="flex h-8 items-center gap-2">
                    <Badge
                      tone={editing.onboarding.status === "completed"
                        ? "success"
                        : editing.onboarding.status === "failed"
                          ? "danger"
                          : "warning"}
                    >
                      {editing.onboarding.status === "completed"
                        ? "已完成"
                        : editing.onboarding.status === "failed"
                          ? "需要处理"
                          : editing.onboarding.status === "running"
                            ? "执行中"
                            : "后台等待"}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {onboardingStageLabels[editing.onboarding.stage] || editing.onboarding.stage}
                    </span>
                  </div>
                </DrawerFormField>
                <DrawerFormField label="状态说明" align="start">
                  <p className="pt-1.5 text-sm leading-5 text-muted-foreground">
                    {editing.onboarding.message || "后台自动接入将在几秒内开始。"}
                  </p>
                </DrawerFormField>
                {editing.onboarding.nameservers.length ? (
                  <DrawerFormField label="域名服务器" align="start">
                    <div className="space-y-1 pt-1">
                      {editing.onboarding.nameservers.map((nameserver) => (
                        <code key={nameserver} className="block break-all text-sm">{nameserver}</code>
                      ))}
                    </div>
                  </DrawerFormField>
                ) : null}
                <DrawerFormField label="操作">
                  <div className="flex min-h-8 flex-wrap items-center gap-2">
                    {editing.onboarding.canContinue ? (
                      <Button
                        variant="outline"
                        disabled={!editing.id || onboardingPending === editing.id}
                        onClick={() => void continueOnboarding(editing)}
                      >
                        {onboardingPending === editing.id ? <Spinner /> : <PlayCircleIcon size={16} />}
                        立即重试
                      </Button>
                    ) : null}
                    <Button
                      variant="outline"
                      disabled={!editing.id || testing === editing.id}
                      onClick={() => void verify(editing)}
                    >
                      {testing === editing.id ? <LoaderCircleIcon className="spin" size={16} /> : <RefreshCwIcon size={16} />}
                      重新验证
                    </Button>
                  </div>
                </DrawerFormField>
              </DrawerFormSection>
            ) : null}
            {editing?.connection?.cname?.target || editing?.connection?.txt?.value ? (
              <DrawerFormSection title="接入记录">
                <DrawerFormField label="CNAME" align="start">
                  <div className="space-y-1 pt-1 text-sm">
                    <code className="block break-all">{editing.connection.cname?.name}</code>
                    <code className="block break-all text-muted-foreground">{editing.connection.cname?.target}</code>
                  </div>
                </DrawerFormField>
                <DrawerFormField label="TXT" align="start">
                  <div className="space-y-1 pt-1 text-sm">
                    <code className="block break-all">{editing.connection.txt?.name}</code>
                    <code className="block break-all text-muted-foreground">{editing.connection.txt?.value}</code>
                  </div>
                </DrawerFormField>
              </DrawerFormSection>
            ) : null}
          </DrawerFormLayout>
        </div>
      </Drawer>
      <Drawer
        open={purchaseOpen}
        onClose={() => !purchasePending && setPurchaseOpen(false)}
        title="购买域名"
        footer={
          <>
            <Button variant="outline" onClick={() => setPurchaseOpen(false)} disabled={purchasePending}>关闭</Button>
            {quote ? (
              <Button onClick={() => void createOrder()} disabled={purchasePending}>
                {purchasePending ? <Spinner /> : null}确认并创建订单
              </Button>
            ) : order?.allowedActions.mockPayment ? (
              <Button disabled={Boolean(orderPending)} onClick={() => void runOrderAction(order, "mock-payment")}>
                {orderPending ? <Spinner /> : null}确认支付并开通
              </Button>
            ) : order?.allowedActions.provision ? (
              <Button disabled={Boolean(orderPending)} onClick={() => void runOrderAction(order, "provision")}>
                {orderPending ? <Spinner /> : null}{order.provider === "namesilo" ? "确认购买并开通" : "立即开通"}
              </Button>
            ) : order ? null : (
              <Button
                onClick={() => void (purchaseHostname ? requestQuote() : requestDomainSearch())}
                disabled={
                  purchasePending
                  || waitingForDomainSearch
                  || (!purchaseHostname && !purchaseLabel.trim())
                }
              >
                {purchasePending || waitingForDomainSearch ? <Spinner /> : null}
                {purchaseHostname ? "确认所选域名" : domainSearch ? "重新查询后缀" : "查询可购买域名"}
              </Button>
            )}
          </>
        }
      >
        <div className="drawer-form">
          <DrawerFormLayout>
            <DrawerFormSection
              title="查询条件"
              description="输入域名主体后，系统会读取 NameSilo 当前后缀价格，并分批查询可注册状态。"
            >
              <DrawerFormField label="域名主体" htmlFor="domain-purchase-label" required>
                <Input
                  id="domain-purchase-label"
                  value={purchaseLabel}
                  disabled={Boolean(quote || order) || domainSearch?.status === "running"}
                  onChange={(event) => {
                    setPurchaseLabel(event.target.value);
                    setPurchaseHostname("");
                    setDomainSearch(null);
                    setQuote(null);
                  }}
                  placeholder="例如：brand 或 brand.shop"
                />
              </DrawerFormField>
              <DrawerFormField label="购买年限" htmlFor="domain-purchase-years" required>
                <Input
                  id="domain-purchase-years"
                  type="number"
                  min="1"
                  max="10"
                  value={purchaseYears}
                  disabled={Boolean(quote || order) || domainSearch?.status === "running"}
                  onChange={(event) => {
                    setPurchaseYears(event.target.value);
                    setPurchaseHostname("");
                    setDomainSearch(null);
                    setQuote(null);
                  }}
                />
              </DrawerFormField>
              <DrawerFormField
                label="自动续费"
                hint="域名购买完成后，由注册商按账户支付设置执行续费。"
              >
                <div className="flex h-8 items-center gap-3">
                  <Switch checked={autoRenew} disabled={Boolean(order)} onCheckedChange={setAutoRenew} />
                  <span className="text-sm">{autoRenew ? "启用" : "关闭"}</span>
                </div>
              </DrawerFormField>
            </DrawerFormSection>

            {domainSearch ? (
              <DrawerFormSection title="可购买后缀">
                <DrawerFormField label="查询进度" align="start">
                  <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-sm">
                    {domainSearch.status === "running" ? <Spinner /> : null}
                    <span>
                      已查询 {domainSearch.searchedCount}
                      {domainSearch.candidateCount ? ` / ${domainSearch.candidateCount}` : ""} 个后缀
                    </span>
                    <span className="text-muted-foreground">
                      找到 {domainSearch.options.length} 个可购买域名
                    </span>
                    {domainSearch.skippedCount ? (
                      <span className="text-[var(--warning)]">跳过 {domainSearch.skippedCount} 个</span>
                    ) : null}
                  </div>
                </DrawerFormField>
                {domainSearch.options.length ? (
                  <>
                    <DrawerFormField label="筛选结果" htmlFor="domain-result-filter">
                      <Input
                        id="domain-result-filter"
                        value={resultKeyword}
                        onChange={(event) => setResultKeyword(event.target.value)}
                        placeholder="搜索后缀或完整域名"
                      />
                    </DrawerFormField>
                    <div className="md:col-span-2">
                      <div className="grid grid-cols-[minmax(0,1fr)_100px_100px] gap-3 border-y px-3 py-2 text-xs font-medium text-muted-foreground">
                        <span>域名 / 后缀</span>
                        <span className="text-right">注册费用</span>
                        <span className="text-right">续费 / 年</span>
                      </div>
                      <div className="max-h-80 overflow-y-auto border-b">
                        {visibleDomainOptions.map((option) => {
                          const selected = purchaseHostname === option.domain;
                          return (
                            <button
                              key={option.domain}
                              type="button"
                              aria-pressed={selected}
                              className={`grid w-full grid-cols-[minmax(0,1fr)_100px_100px] items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/60 ${selected ? "bg-primary/5" : ""}`}
                              onClick={() => {
                                setPurchaseHostname(option.domain);
                                setQuote(null);
                                setOrder(null);
                              }}
                            >
                              <span className="flex min-w-0 items-center gap-2">
                                <span className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${selected ? "border-primary bg-primary" : "border-input"}`}>
                                  {selected ? <span className="size-1.5 rounded-full bg-primary-foreground" /> : null}
                                </span>
                                <span className="min-w-0">
                                  <strong className="block truncate font-medium">{option.domain}</strong>
                                  <span className="text-xs text-muted-foreground">.{option.domain.slice(domainSearch.label.length + 1)}</span>
                                </span>
                              </span>
                              <span className="text-right tabular-nums">
                                {option.currency} {option.registrationPrice.toFixed(2)}
                              </span>
                              <span className="text-right tabular-nums text-muted-foreground">
                                {option.renewalPrice == null ? "-" : `${option.currency} ${option.renewalPrice.toFixed(2)}`}
                              </span>
                            </button>
                          );
                        })}
                        {!visibleDomainOptions.length ? (
                          <div className="px-3 py-8 text-center text-sm text-muted-foreground">没有匹配的后缀</div>
                        ) : null}
                      </div>
                    </div>
                  </>
                ) : domainSearch.status === "completed" ? (
                  <DrawerFormField label="查询结果">
                    <div className="flex h-8 items-center text-sm text-muted-foreground">没有找到可购买的域名后缀</div>
                  </DrawerFormField>
                ) : null}
                {domainSearch.error ? (
                  <DrawerFormField label="失败原因" align="start">
                    <p className="pt-1.5 text-sm text-destructive">{domainSearch.error}</p>
                  </DrawerFormField>
                ) : null}
              </DrawerFormSection>
            ) : null}

            {quote ? (
              <DrawerFormSection title="报价确认">
                <DrawerFormField label="域名">
                  <div className="flex h-8 items-center text-sm font-medium">{String(quote.hostname || purchaseHostname)}</div>
                </DrawerFormField>
                <DrawerFormField label="当前报价">
                  <div className="flex h-8 items-center text-sm">
                    <strong className="font-medium tabular-nums">
                      {String(quote.currency || "USD")} {Number(quote.amount || 0).toFixed(2)}
                    </strong>
                    <span className="ml-2 text-muted-foreground">{String(quote.years || purchaseYears)} 年</span>
                  </div>
                </DrawerFormField>
                <DrawerFormField label="有效期">
                  <div className="flex h-8 items-center text-sm text-muted-foreground">
                    {formatDateTime(String(quote.expiresAt || ""))}
                  </div>
                </DrawerFormField>
              </DrawerFormSection>
            ) : null}

            {order ? (
              <DrawerFormSection title="订单状态">
                <DrawerFormField label="域名">
                  <div className="flex h-8 items-center text-sm font-medium">{order.hostname || purchaseHostname}</div>
                </DrawerFormField>
                <DrawerFormField label="当前状态">
                  <div className="flex h-8 items-center gap-2 text-sm">
                    <Badge tone={order.status === "completed" ? "success" : order.status === "failed" ? "danger" : "warning"}>
                      {orderStatusLabels[order.status] || order.status}
                    </Badge>
                    <span className="text-muted-foreground">{order.id}</span>
                  </div>
                </DrawerFormField>
                {order.failureReason ? (
                  <DrawerFormField label="状态说明" align="start">
                    <p className="pt-1.5 text-sm text-destructive">{order.failureReason}</p>
                  </DrawerFormField>
                ) : null}
              </DrawerFormSection>
            ) : null}
          </DrawerFormLayout>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
