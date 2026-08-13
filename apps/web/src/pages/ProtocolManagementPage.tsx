import {
  ArrowDownToLineIcon,
  ArrowUpFromLineIcon,
  LoaderCircleIcon,
  PencilIcon,
  RefreshCwIcon,
  ServerCogIcon,
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
  Textarea,
  toast,
} from "../components/ui";

const COOLDOWN_KEY = "parloq-protocol-batch-cooldown-until";

type ProtocolNode = {
  id: string;
  name: string;
  ingressEnabled: boolean;
  marketingEnabled: boolean;
  online: boolean;
  totalCount: number | null;
  validCount: number | null;
  validRate: number | null;
  onlineCount: number | null;
  onlineRate: number | null;
  remark: string;
  createdAt: string;
};

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
  const totalCount = number(row, "totalCount", "total_count", "accountTotal", "account_total", "accountCount", "account_count");
  const validCount = number(row, "validCount", "valid_count", "validAccounts", "valid_accounts", "effectiveCount", "effective_count");
  const onlineCount = number(row, "onlineCount", "online_count", "onlineAccounts", "online_accounts");
  return {
    id: text(row, "publicId", "public_id", "id"),
    name: text(row, "name", "title"),
    ingressEnabled: boolean(row, true, "ingressEnabled", "ingress_enabled", "accountIngressEnabled", "account_ingress_enabled", "allowIngress", "allow_ingress"),
    marketingEnabled: boolean(row, true, "marketingEnabled", "marketing_enabled", "allowMarketing", "allow_marketing"),
    online: boolean(row, true, "online", "onlineEnabled", "online_enabled"),
    totalCount,
    validCount,
    validRate: normalizeRate(number(row, "validRate", "valid_rate", "effectiveRate", "effective_rate"), validCount, totalCount),
    onlineCount,
    onlineRate: normalizeRate(number(row, "onlineRate", "online_rate"), onlineCount, validCount),
    remark: text(row, "remark", "note", "description"),
    createdAt: text(row, "createdAt", "created_at"),
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<ProtocolNode | null>(null);
  const [form, setForm] = useState({
    name: "",
    ingressEnabled: true,
    marketingEnabled: true,
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
      const payload = await apiRequest("/api/protocol-nodes?pageSize=100");
      const nextRows = unwrapList<unknown>(payload).rows.map(protocolNode);
      setRows(nextRows);
      setSelected((current) => current.filter((id) => nextRows.some((row) => row.id === id)));
    } catch (caught) {
      setRows([]);
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
  const visibleIds = visible.map((row) => row.id);
  const allVisibleSelected = Boolean(visibleIds.length) && visibleIds.every((id) => selected.includes(id));
  const remainingSeconds = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));

  function openEdit(row: ProtocolNode) {
    setEditing(row);
    setForm({
      name: row.name,
      ingressEnabled: row.ingressEnabled,
      marketingEnabled: row.marketingEnabled,
      remark: row.remark,
    });
  }
  async function save() {
    if (!editing || !form.name.trim()) return;
    setSaving(true);
    try {
      await apiRequest(`/api/protocol-nodes/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: form.name.trim(),
          ingressEnabled: form.ingressEnabled,
          marketingEnabled: form.marketingEnabled,
          remark: form.remark.trim() || null,
        }),
      });
      setEditing(null);
      await load();
      toast.success("协议设置已保存");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setSaving(false);
    }
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
    <StandardListPage>
      <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        协议节点用于批量管控一组账号。进号开关影响后续账号接入；营销开关关闭后，该节点账号会被营销任务跳过。
      </div>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索协议名称、ID 或备注" }}
        meta={selected.length ? `已选择 ${selected.length} 个协议` : `${visible.length} 个协议`}
        actions={
          <>
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
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载协议节点…</div> : error ? (
          <div className="error-state"><strong>协议加载失败</strong><span>{error}</span><Button variant="outline" onClick={() => void load()}>重试</Button></div>
        ) : visible.length ? (
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-10"><Checkbox aria-label="选择全部协议" checked={allVisibleSelected} onCheckedChange={(checked) => setSelected(checked ? Array.from(new Set([...selected, ...visibleIds])) : selected.filter((id) => !visibleIds.includes(id)))} /></TableHead>
              <TableHead>协议名称</TableHead><TableHead>运行状态</TableHead><TableHead>进号开关</TableHead><TableHead>营销开关</TableHead><TableHead>账号总量</TableHead><TableHead>有效数 / 率</TableHead><TableHead>在线数 / 率</TableHead><TableHead>备注</TableHead><TableHead>创建时间</TableHead><TableHead className="text-right">操作</TableHead>
            </TableRow></TableHeader>
            <TableBody>{visible.map((row) => <TableRow key={row.id}>
              <TableCell><Checkbox aria-label={`选择协议 ${row.name || row.id}`} checked={selected.includes(row.id)} onCheckedChange={(checked) => setSelected((current) => checked ? [...current, row.id] : current.filter((id) => id !== row.id))} /></TableCell>
              <TableCell><div className="cell-main"><strong>{row.name || `#${row.id}`}</strong><span>#{row.id}</span></div></TableCell>
              <TableCell><Badge tone={row.online ? "success" : "neutral"}>{row.online ? "已上线" : "已下线"}</Badge></TableCell>
              <TableCell><Badge tone={row.ingressEnabled ? "success" : "neutral"}>{row.ingressEnabled ? "已开启" : "已关闭"}</Badge></TableCell>
              <TableCell><Badge tone={row.marketingEnabled ? "success" : "neutral"}>{row.marketingEnabled ? "已开启" : "已关闭"}</Badge></TableCell>
              <TableCell>{row.totalCount == null ? <span className="text-muted-foreground">-</span> : row.totalCount.toLocaleString()}</TableCell>
              <TableCell><div className="flex items-center gap-2"><span>{row.validCount == null ? "-" : row.validCount.toLocaleString()}</span>{rateBadge(row.validRate, "valid")}</div></TableCell>
              <TableCell><div className="flex items-center gap-2"><span>{row.onlineCount == null ? "-" : row.onlineCount.toLocaleString()}</span>{rateBadge(row.onlineRate, "online")}</div></TableCell>
              <TableCell><span className="block max-w-52 truncate text-muted-foreground" title={row.remark}>{row.remark || "-"}</span></TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              <TableCell><div className="flex justify-end">{canManage ? <IconButton label="编辑协议" onClick={() => openEdit(row)}><PencilIcon size={15} /></IconButton> : null}</div></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        ) : <EmptyState title="暂无协议节点" description="协议节点由系统接入配置创建，当前没有可管理的节点。" />}
      </ListTableCard>
      <Drawer
        open={Boolean(editing)}
        onClose={() => !saving && setEditing(null)}
        title={`编辑协议 · #${editing?.id || ""}`}
        description="技术连接地址由系统维护，此处只配置运营侧名称与开关。"
        footer={<><Button variant="outline" disabled={saving} onClick={() => setEditing(null)}>取消</Button><Button disabled={saving || !form.name.trim() || form.name.trim().length > 64 || form.remark.length > 512} onClick={() => void save()}>{saving ? <LoaderCircleIcon className="spin" size={16} /> : null}保存</Button></>}
      >
        <div className="drawer-form">
          <label className="field"><span>协议名称</span><Input maxLength={64} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="请输入协议名称，用于识别区分不同协议" /><small>{form.name.length} / 64</small></label>
          <label className="switch-row"><span><strong>进号开关</strong><small>关闭后暂停新账号通过该节点接入，不影响已在线账号。</small></span><Switch checked={form.ingressEnabled} onCheckedChange={(checked) => setForm((current) => ({ ...current, ingressEnabled: checked }))} aria-label="进号开关" /></label>
          <label className="switch-row"><span><strong>营销开关</strong><small>关闭后该节点账号不会被营销任务选中，账号连接不受影响。</small></span><Switch checked={form.marketingEnabled} onCheckedChange={(checked) => setForm((current) => ({ ...current, marketingEnabled: checked }))} aria-label="营销开关" /></label>
          <label className="field"><span>备注</span><Textarea rows={5} maxLength={512} value={form.remark} onChange={(event) => setForm((current) => ({ ...current, remark: event.target.value }))} placeholder="请输入备注（可选，最多 512 字）" /><small>{form.remark.length} / 512</small></label>
        </div>
      </Drawer>
    </StandardListPage>
  );
}
