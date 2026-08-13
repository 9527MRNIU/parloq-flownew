import {
  LoaderCircleIcon,
  PencilIcon,
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
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import { useAuth } from "../auth/AuthContext";

type DomainRow = {
  id: string;
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
};
type DomainOrderRow = {
  id: string;
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
const get = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};
function normalize(input: unknown): DomainRow {
  const row = input as Record<string, unknown>;
  return {
    id: get(row, "publicId", "public_id", "id"),
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
  };
}
function normalizeOrder(input: unknown): DomainOrderRow {
  const row = input as Record<string, unknown>;
  const allowed = (row.allowedActions && typeof row.allowedActions === "object"
    ? row.allowedActions
    : row.allowed_actions || {}) as Record<string, unknown>;
  return {
    id: get(row, "publicId", "public_id", "id"),
    hostname: get(row, "hostname"),
    years: Number(row.years || 1),
    amount: Number(row.amount || 0),
    currency: get(row, "currency") || "USD",
    status: get(row, "status") || "pending_payment",
    provider: get(row, "provider"),
    autoRenew: Boolean(row.autoRenew ?? row.auto_renew),
    failureReason: get(row, "failureReason", "failure_reason"),
    domainId: get(row, "domainId", "domain_id"),
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
function statusBadge(status: string) {
  if (["verified", "active", "ready", "valid"].includes(status))
    return <Badge tone="success">正常</Badge>;
  if (["failed", "invalid", "error"].includes(status))
    return <Badge tone="danger">异常</Badge>;
  return <Badge tone="warning">待验证</Badge>;
}
const orderStatusLabels: Record<string, string> = {
  pending_payment: "待支付",
  paid: "已支付",
  provisioning: "开通中",
  unknown: "结果待确认",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};
function orderStatusBadge(status: string) {
  const tone = status === "completed"
    ? "success"
    : status === "failed"
      ? "danger"
      : ["pending_payment", "paid", "provisioning", "unknown"].includes(status)
        ? "warning"
        : "neutral";
  return <Badge tone={tone}>{orderStatusLabels[status] || status}</Badge>;
}
export function DomainsPage() {
  const { can } = useAuth();
  const canManage = can("promotion.domain.manage");
  const canPurchase = can("promotion.domain.purchase");
  const [rows, setRows] = useState<DomainRow[]>([]);
  const [orders, setOrders] = useState<DomainOrderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<DomainRow | null>(null);
  const [hostname, setHostname] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [pending, setPending] = useState(false);
  const [testing, setTesting] = useState("");
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [purchaseHostname, setPurchaseHostname] = useState("");
  const [purchaseYears, setPurchaseYears] = useState("1");
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
  function open(row?: DomainRow) {
    setEditing(row || null);
    setHostname(row?.hostname || "");
    setEnabled(row?.enabled ?? true);
    setDrawer(true);
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
      if (saved) setEditing(normalize(saved));
      if (editing) setDrawer(false);
      await load();
      toast.success(editing ? "域名已更新" : "域名已接入，请完成解析验证");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
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
    if (action === "cancel" && !(await confirmAction({
      title: `取消域名订单 ${row.hostname}？`,
      description: "取消后需要重新询价才能再次购买。",
      confirmText: "确认取消",
    }))) return;
    setOrderPending(`${row.id}:${action}`);
    try {
      let payload = await apiRequest(`/api/domain-orders/${row.id}/${action}`, { method: "POST" });
      let nextValue = (payload as { data?: { order?: unknown } }).data?.order;
      let updated = nextValue ? normalizeOrder(nextValue) : row;
      if (action === "mock-payment" && updated.allowedActions.provision) {
        payload = await apiRequest(`/api/domain-orders/${row.id}/provision`, { method: "POST" });
        nextValue = (payload as { data?: { order?: unknown } }).data?.order;
        updated = nextValue ? normalizeOrder(nextValue) : updated;
      }
      if (order?.id === row.id) setOrder(updated);
      await load();
      toast.success(
        action === "cancel"
          ? "订单已取消"
          : updated.status === "completed"
            ? "域名已开通，接下来可完成解析验证"
            : updated.status === "unknown"
              ? "注册结果待确认，请执行订单对账"
              : "订单状态已更新",
      );
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "订单操作失败");
    } finally {
      setOrderPending("");
    }
  }
  async function remove(row: DomainRow) {
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
    <StandardListPage>
      <ListToolbar
        search={{
          value: keyword,
          onChange: setKeyword,
          placeholder: "搜索域名",
        }}
        meta={`${visible.length} 个域名`}
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCwIcon size={16} />
              刷新
            </Button>
            {canManage ? (
              <Button variant="outline" onClick={() => open()}>
                <PlusIcon size={17} />
                接入已有域名
              </Button>
            ) : null}
            {canPurchase ? (
              <Button onClick={() => {
                setPurchaseHostname("");
                setPurchaseYears("1");
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
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <strong>{row.hostname}</strong>
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
                      <Badge tone={row.enabled ? "success" : "neutral"}>
                        {row.enabled ? "启用" : "停用"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {canManage ? (
                          <>
                            <IconButton
                              label="立即验证"
                              disabled={testing === row.id}
                              onClick={() => void verify(row)}
                            >
                              {testing === row.id ? (
                                <LoaderCircleIcon className="spin" size={16} />
                              ) : (
                                <RefreshCwIcon size={16} />
                              )}
                            </IconButton>
                            <IconButton label="编辑" onClick={() => open(row)}>
                              <PencilIcon size={16} />
                            </IconButton>
                            <IconButton
                              label="归档"
                              variant="ghost"
                              className="danger"
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
      <ListTableCard>
        {loading ? (
          <div className="loading-state"><Spinner /></div>
        ) : orders.length ? (
          <div className="table-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>域名订单</TableHead>
                  <TableHead>年限</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>注册商</TableHead>
                  <TableHead>订单状态</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.map((row) => {
                  const busy = orderPending.startsWith(`${row.id}:`);
                  return (
                    <TableRow key={row.id}>
                      <TableCell>
                        <div className="cell-main">
                          <strong>{row.hostname}</strong>
                          <span>{row.id}</span>
                          {row.failureReason ? <span className="danger-text">{row.failureReason}</span> : null}
                        </div>
                      </TableCell>
                      <TableCell>{row.years} 年</TableCell>
                      <TableCell className="tabular-nums">{row.currency} {row.amount.toFixed(2)}</TableCell>
                      <TableCell>{row.provider || "-"}</TableCell>
                      <TableCell>{orderStatusBadge(row.status)}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {canPurchase && row.allowedActions.mockPayment ? (
                            <Button size="sm" disabled={busy} onClick={() => void runOrderAction(row, "mock-payment")}>
                              {busy ? <Spinner /> : null}确认支付并开通
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.provision ? (
                            <Button size="sm" disabled={busy} onClick={() => void runOrderAction(row, "provision")}>
                              {busy ? <Spinner /> : null}立即开通
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.reconcile ? (
                            <Button size="sm" variant="outline" disabled={busy} onClick={() => void runOrderAction(row, "reconcile")}>
                              {busy ? <Spinner /> : null}订单对账
                            </Button>
                          ) : null}
                          {canPurchase && row.allowedActions.cancel ? (
                            <Button size="sm" variant="ghost" className="danger" disabled={busy} onClick={() => void runOrderAction(row, "cancel")}>
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
      <Drawer
        open={drawer}
        onClose={() => !pending && setDrawer(false)}
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
          <label className="field">
            <span>域名</span>
            <Input
              value={hostname}
              disabled={Boolean(editing)}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="go.example.com"
            />
          </label>
          {editing?.connection?.cname?.target || editing?.connection?.txt?.value ? (
            <div className="dns-records">
              <strong>DNS 解析记录</strong>
              <div><span>CNAME</span><code>{editing.connection.cname?.name}</code><code>{editing.connection.cname?.target}</code></div>
              <div><span>TXT</span><code>{editing.connection.txt?.name}</code><code>{editing.connection.txt?.value}</code></div>
              <Button variant="outline" disabled={testing === editing.id} onClick={() => void verify(editing)}>
                {testing === editing.id ? <LoaderCircleIcon className="spin" size={16} /> : <RefreshCwIcon size={16} />}
                验证解析
              </Button>
            </div>
          ) : null}
          <label className="switch-row">
            <span>
              <strong>启用域名</strong>
              <small>停用后不会分配给新的推广渠道。</small>
            </span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>
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
                {orderPending ? <Spinner /> : null}立即开通
              </Button>
            ) : order?.allowedActions.reconcile ? (
              <Button disabled={Boolean(orderPending)} onClick={() => void runOrderAction(order, "reconcile")}>
                {orderPending ? <Spinner /> : null}订单对账
              </Button>
            ) : order ? null : (
              <Button onClick={() => void requestQuote()} disabled={purchasePending || !purchaseHostname.trim()}>
                {purchasePending ? <Spinner /> : null}查询价格
              </Button>
            )}
          </>
        }
      >
        <div className="drawer-form">
          <label className="field">
            <span>完整域名</span>
            <Input value={purchaseHostname} disabled={Boolean(quote || order)} onChange={(event) => setPurchaseHostname(event.target.value)} placeholder="example.com" />
          </label>
          <label className="field">
            <span>购买年限</span>
            <Input type="number" min="1" max="10" value={purchaseYears} disabled={Boolean(quote || order)} onChange={(event) => setPurchaseYears(event.target.value)} />
          </label>
          {quote ? (
            <div className="quote-card">
              <span>当前报价</span>
              <strong>{String(quote.currency || "USD")} {Number(quote.amount || 0).toFixed(2)}</strong>
              <small>{String(quote.years || purchaseYears)} 年 · 报价有效期至 {formatDateTime(String(quote.expiresAt || ""))}</small>
            </div>
          ) : null}
          {order ? (
            <div className="quote-card order-status-card">
              <span>订单已创建</span>
              <strong>{order.hostname || purchaseHostname}</strong>
              <small>状态：{orderStatusLabels[order.status] || order.status} · 订单号 {order.id || "-"}</small>
              {order.failureReason ? <small className="danger-text">{order.failureReason}</small> : null}
            </div>
          ) : null}
          <label className="switch-row">
            <span><strong>自动续费</strong><small>注册商支持且续费能力启用后生效。</small></span>
            <Switch checked={autoRenew} disabled={Boolean(order)} onCheckedChange={setAutoRenew} />
          </label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
