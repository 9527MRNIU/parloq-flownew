import {
  LoaderCircleIcon,
  PencilIcon,
  PlayCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  ShoppingCartIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, formatDateTime, unwrapList } from "../api/client";
import {
  Badge,
  Button,
  confirmAction,
  Drawer,
  EmptyState,
  IconButton,
  Input,
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
  ListTableCard,
  ListToolbar,
  StandardListPage,
  useClientPagination,
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
    reconcile: boolean;
    cancel: boolean;
  };
  createdAt?: string;
  updatedAt?: string;
};
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
      reconcile: Boolean(allowed.reconcile),
      cancel: Boolean(allowed.cancel),
    },
    createdAt: get(row, "createdAt", "created_at"),
    updatedAt: get(row, "updatedAt", "updated_at"),
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
export function DomainsPage() {
  const { can } = useAuth();
  const canManage = can("promotion.domain.manage");
  const canPurchase = can("promotion.domain.purchase");
  const [rows, setRows] = useState<DomainRow[]>([]);
  const [orders, setOrders] = useState<DomainOrderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeList, setActiveList] = useState<"domains" | "orders">("domains");
  const [keyword, setKeyword] = useState("");
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
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [domainPayload, orderPayload] = await Promise.all([
        apiRequest("/api/domains?pageSize=100"),
        apiRequest("/api/domain-orders"),
      ]);
      setRows(unwrapList<unknown>(domainPayload).rows.map(normalize));
      setOrders(unwrapList<unknown>(orderPayload).rows.map(normalizeOrder));
    } catch {
      setRows([]);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? rows.filter((row) => row.hostname.toLowerCase().includes(search))
      : rows;
  }, [keyword, rows]);
  const visibleOrders = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return search
      ? orders.filter((row) => row.hostname.toLowerCase().includes(search))
      : orders;
  }, [keyword, orders]);
  const domainPagination = useClientPagination(visible, {
    resetKey: `${activeList}|${keyword}`,
  });
  const orderPagination = useClientPagination(visibleOrders, {
    resetKey: `${activeList}|${keyword}`,
  });
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
  function open(row?: DomainRow) {
    setEditing(row || null);
    setHostname(row?.hostname || "");
    setEnabled(row?.enabled ?? true);
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
    if (!hostname.trim()) return;
    setPending(true);
    try {
      const payload = await apiRequest(
        editing ? `/api/domains/${editing.id}` : "/api/domains",
        {
          method: editing ? "PATCH" : "POST",
          body: JSON.stringify({
            hostname: hostname
              .trim()
              .toLowerCase()
              .replace(/^https?:\/\//, "")
              .replace(/\/$/, ""),
            enabled,
            managementMode: "external",
          }),
        },
      );
      const saved = (payload as { data?: { domain?: unknown } }).data?.domain;
      const savedRow = saved ? normalize(saved) : null;
      if (savedRow) setEditing(savedRow);
      if (editing) setDrawer(false);
      await load();
      if (editing) {
        toast.success("域名已更新");
      } else if (savedRow) {
        toast.success("域名记录已创建，正在启动自动接入");
        await continueOnboarding(savedRow);
      }
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
  async function runOrderAction(row: DomainOrderRow, action: "mock-payment" | "provision" | "reconcile" | "cancel") {
    if (!row.id) return;
    if (action === "provision" && row.provider === "namesilo" && !(await confirmAction({
      title: `确认通过 NameSilo 购买 ${row.hostname}？`,
      description: `确认后将立即向 NameSilo 提交 ${row.years} 年购买请求，预计金额 ${row.currency} ${row.amount.toFixed(2)}。将使用系统配置中已明确选择的 NameSilo 支付方式。`,
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
              ? "注册结果待确认，请执行订单对账"
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
  async function remove(row: DomainRow) {
    if (!row.id) return;
    if (
      !(await confirmAction({
        title: `归档域名 ${row.hostname}？`,
        description: "归档后该域名将不再用于新的推广渠道。",
        confirmText: "确认归档",
      }))
    )
      return;
    try {
      await apiRequest(`/api/domains/${row.id}`, { method: "DELETE" });
      await load();
      toast.success("域名已归档");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "归档失败");
    }
  }
  return (
    <StandardListPage viewport>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: activeList === "domains" ? "搜索域名" : "搜索购买记录",
        }}
        filters={
          <div className="flex items-center gap-2">
            <Button
              variant={activeList === "domains" ? "secondary" : "outline"}
              aria-pressed={activeList === "domains"}
              onClick={() => {
                setActiveList("domains");
                setKeyword("");
              }}
            >
              域名列表
            </Button>
            <Button
              variant={activeList === "orders" ? "secondary" : "outline"}
              aria-pressed={activeList === "orders"}
              onClick={() => {
                setActiveList("orders");
                setKeyword("");
              }}
            >
              购买记录
            </Button>
          </div>
        }
        meta={activeList === "domains" ? `${visible.length} 个域名` : `${visibleOrders.length} 条记录`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage && activeList === "domains" ? (
              <Button variant="outline" onClick={() => open()}>
                <PlusIcon size={17} />
                接入已有域名
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
      {activeList === "domains" ? (
        <ListPagination
          page={domainPagination.page}
          pageSize={domainPagination.pageSize}
          total={domainPagination.total}
          disabled={loading}
          onPageChange={domainPagination.setPage}
          onPageSizeChange={domainPagination.setPageSize}
        />
      ) : (
        <ListPagination
          ariaLabel="购买记录分页"
          page={orderPagination.page}
          pageSize={orderPagination.pageSize}
          total={orderPagination.total}
          disabled={loading}
          onPageChange={orderPagination.setPage}
          onPageSizeChange={orderPagination.setPageSize}
        />
      )}
      {activeList === "domains" ? (
        <ListTableCard>
        {loading ? (
          <div className="loading-state">
            <Spinner />
          </div>
        ) : visible.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>域名</TableHead>
                  <TableHead>来源 / 托管</TableHead>
                  <TableHead>DNS / TLS</TableHead>
                  <TableHead>就绪状态</TableHead>
                  <TableHead>到期时间</TableHead>
                  <TableHead>绑定渠道</TableHead>
                  <TableHead>最近验证</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {domainPagination.rows.map((row) => (
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
                      <div className="cell-main">
                        <strong>{row.acquisitionType === "purchased" ? "平台购买" : "外部接入"}</strong>
                        <span>{row.managementMode === "platform" ? "平台托管" : "自行管理"}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="domain-status-pair">
                        <span>DNS {statusBadge(row.dnsStatus)}</span>
                        <span>TLS {statusBadge(row.sslStatus)}</span>
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
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {canManage ? (
                          <>
                            {row.onboarding.canContinue ? (
                              <IconButton
                                label="继续自动接入"
                                disabled={!row.id || onboardingPending === row.id}
                                onClick={() => void continueOnboarding(row)}
                              >
                                {onboardingPending === row.id ? (
                                  <LoaderCircleIcon className="spin" size={16} />
                                ) : (
                                  <PlayCircleIcon size={16} />
                                )}
                              </IconButton>
                            ) : null}
                            <IconButton
                              label="立即验证"
                              disabled={!row.id || testing === row.id}
                              onClick={() => void verify(row)}
                            >
                              {testing === row.id ? (
                                <LoaderCircleIcon className="spin" size={16} />
                              ) : (
                                <RefreshCwIcon size={16} />
                              )}
                            </IconButton>
                            <IconButton label="编辑" disabled={!row.id} onClick={() => open(row)}>
                              <PencilIcon size={16} />
                            </IconButton>
                            <IconButton
                              label="归档"
                              variant="ghost"
                              className="danger"
                              disabled={!row.id}
                              onClick={() => void remove(row)}
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
            title="还没有域名"
            description="添加推广域名并完成 DNS、SSL 验证。"
          />
        )}
        </ListTableCard>
      ) : (
        <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner /></div>
        ) : visibleOrders.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>域名订单</TableHead>
                  <TableHead>年限</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>注册商</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orderPagination.rows.map((row) => {
                  const busy = Boolean(row.id) && orderPending.startsWith(`${row.id}:`);
                  return (
                    <TableRow key={row.readKey}>
                      <TableCell>
                        <EntityPrimaryCell
                          title={row.hostname}
                          id={row.id}
                          description={row.failureReason || undefined}
                          status={{
                            ...domainOrderStatus(row),
                            details: [
                              { label: "年限", value: `${row.years} 年` },
                              { label: "金额", value: `${row.currency} ${row.amount.toFixed(2)}` },
                            ],
                          }}
                        />
                      </TableCell>
                      <TableCell>{row.years} 年</TableCell>
                      <TableCell className="tabular-nums">{row.currency} {row.amount.toFixed(2)}</TableCell>
                      <TableCell>{row.provider || "-"}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {canPurchase && row.allowedActions.mockPayment ? (
                            <Button disabled={!row.id || busy} onClick={() => void runOrderAction(row, "mock-payment")}>
                              {busy ? <Spinner /> : null}确认支付并开通
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.provision ? (
                            <Button disabled={!row.id || busy} onClick={() => void runOrderAction(row, "provision")}>
                              {busy ? <Spinner /> : null}{row.provider === "namesilo" ? "确认购买" : "立即开通"}
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.reconcile ? (
                            <Button variant="outline" disabled={!row.id || busy} onClick={() => void runOrderAction(row, "reconcile")}>
                              {busy ? <Spinner /> : null}订单对账
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.cancel ? (
                            <Button variant="ghost" className="danger" disabled={!row.id || busy} onClick={() => void runOrderAction(row, "cancel")}>
                              取消
                            </Button>
                          ) : null}
                          {!canPurchase || !Object.values(row.allowedActions).some(Boolean) ? <span className="text-muted-foreground">-</span> : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState title="暂无域名订单" description="购买域名时，报价和订单进度会显示在这里。" />
        )}
        </ListTableCard>
      )}
      <Drawer
        open={drawer}
        onClose={() => !pending && !onboardingPending && setDrawer(false)}
        title={editing ? "域名接入与验证" : "接入已有域名"}
        footer={
          <>
            <Button variant="outline" onClick={() => setDrawer(false)}>
              取消
            </Button>
            <Button
              disabled={pending || !hostname.trim()}
              onClick={() => void save()}
            >
              {pending ? <Spinner /> : null}{editing ? "保存设置" : "生成接入记录"}
            </Button>
          </>
        }
      >
        <div className="drawer-form">
          <DrawerFormLayout>
            <DrawerFormSection title="基础信息">
              <DrawerFormField label="域名">
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
                description="依次核对 Cloudflare Zone、域名服务器、DNS、宝塔站点和公网可用性。等待外部生效时不会后台重复写入。"
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
                            : "等待继续"}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {onboardingStageLabels[editing.onboarding.stage] || editing.onboarding.stage}
                    </span>
                  </div>
                </DrawerFormField>
                <DrawerFormField label="状态说明" align="start">
                  <p className="pt-1.5 text-sm leading-5 text-muted-foreground">
                    {editing.onboarding.message || "点击继续自动接入开始配置。"}
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
                        继续自动接入
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
            ) : order?.allowedActions.reconcile ? (
              <Button disabled={Boolean(orderPending)} onClick={() => void runOrderAction(order, "reconcile")}>
                {orderPending ? <Spinner /> : null}订单对账
              </Button>
            ) : order ? null : (
              <Button
                onClick={() => void (purchaseHostname ? requestQuote() : requestDomainSearch())}
                disabled={
                  purchasePending
                  || domainSearch?.status === "running"
                  || (!purchaseHostname && !purchaseLabel.trim())
                }
              >
                {purchasePending || domainSearch?.status === "running" ? <Spinner /> : null}
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
              <DrawerFormField label="域名主体" htmlFor="domain-purchase-label">
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
              <DrawerFormField label="购买年限" htmlFor="domain-purchase-years">
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
