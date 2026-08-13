import {
  BarChart3Icon,
  CheckCircle2Icon,
  DownloadIcon,
  FileJsonIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  Trash2Icon,
  UploadCloudIcon,
  UsersIcon,
  WifiIcon,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  apiDownload,
  apiRequest,
  formatDateTime,
  unwrapList,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  ListTableCard,
  ListToolbar,
  StandardListPage,
} from "../components/list-page";
import {
  Badge,
  Button,
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
  phone: string;
  name: string;
  status: string;
  source: string;
  connected: boolean;
  createdAt: string;
};

function exportAccount(input: unknown): ExportAccount {
  const row = input as Record<string, unknown>;
  const status = field(row, "connectionStatus", "connection_status", "status");
  return {
    id: field(row, "publicId", "public_id", "id"),
    phone: field(row, "phoneNumber", "phone_number", "phone"),
    name: field(row, "displayName", "display_name", "name"),
    status: status || "offline",
    source: field(row, "source", "credentialSource", "credential_source"),
    connected: Boolean(
      row.connected ?? ["connected", "online", "online_idle"].includes(status),
    ),
    createdAt: field(row, "createdAt", "created_at"),
  };
}

function sourceBadge(source: string) {
  if (["landing_page", "landing", "pairing"].includes(source))
    return <Badge tone="primary">落地页链接</Badge>;
  if (["json", "json_import", "import"].includes(source))
    return <Badge tone="neutral">JSON 导入</Badge>;
  return <Badge tone="neutral">待识别</Badge>;
}

export function AccountImportPage() {
  const { can, user } = useAuth();
  const canManage =
    can("resources.accounts.import") ||
    can("resources.accounts.manage") ||
    can("business.personal_accounts.manage");
  const [file, setFile] = useState<File | null>(null);
  const [validating, setValidating] = useState(false);
  const [pending, setPending] = useState(false);
  const [validation, setValidation] = useState<{
    valid: boolean;
    message: string;
  } | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [proxyId, setProxyId] = useState("");
  const [proxyOptions, setProxyOptions] = useState<Array<{ value: string; label: string }>>([]);

  useEffect(() => {
    if (!user?.isAdmin) return;
    void apiRequest("/api/ip-proxies?pageSize=100")
      .then((payload) => {
        setProxyOptions(
          unwrapList<Record<string, unknown>>(payload).rows.map((row) => ({
            value: field(row, "publicId", "public_id", "id"),
            label: [
              field(row, "name"),
              field(row, "countryCode", "country_code"),
              field(row, "host"),
            ].filter(Boolean).join(" · "),
          })).filter((option) => option.value),
        );
      })
      .catch(() => setProxyOptions([]));
  }, [user?.isAdmin]);

  async function choose(next: File | null) {
    setFile(next);
    setResult(null);
    setValidation(null);
    if (!next) return;
    setValidating(true);
    try {
      if (!next.name.toLowerCase().endsWith(".json"))
        throw new Error("请选择 .json 文件");
      if (next.size > 10 * 1024 * 1024)
        throw new Error("JSON 文件不能超过 10 MB");
      const parsed = JSON.parse(await next.text()) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("JSON 顶层必须是对象");
      setValidation({
        valid: true,
        message: "文件结构可解析；服务器将在入库前校验 Baileys 凭据完整性。",
      });
    } catch (caught) {
      setValidation({
        valid: false,
        message: caught instanceof Error ? caught.message : "JSON 无法解析",
      });
    } finally {
      setValidating(false);
    }
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!file || !validation?.valid || !canManage) return;
    setPending(true);
    setResult(null);
    try {
      const body = new FormData();
      body.set("file", file);
      if (proxyId) body.set("proxyPublicId", proxyId);
      const payload = await apiRequest("/api/personal-accounts/import", {
        method: "POST",
        body,
      });
      const data = (payload as { data?: Record<string, unknown> }).data;
      const account = data?.account;
      setResult(
        account && typeof account === "object" && !Array.isArray(account)
          ? (account as Record<string, unknown>)
          : data || (payload as Record<string, unknown>),
      );
      toast.success("账号 JSON 已导入统一账号池");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <StandardListPage>
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <form className="card flex min-h-[420px] flex-col gap-5" onSubmit={submit}>
          <div className="flex items-start gap-3">
            <span className="summary-icon"><FileJsonIcon size={19} /></span>
            <div className="cell-main">
              <strong>导入 Baileys 账号 JSON</strong>
              <span>导入后先校验凭据并尝试恢复连接，验证成功才进入可用账号池。</span>
            </div>
          </div>
          <label className="upload-zone min-h-56">
            <Input
              type="file"
              accept=".json,application/json"
              disabled={pending || !canManage}
              onChange={(event) => void choose(event.target.files?.[0] || null)}
            />
            {validating ? <Spinner /> : <UploadCloudIcon size={30} />}
            <strong>{file?.name || "选择账号 JSON 文件"}</strong>
            <span>支持 Baileys creds JSON 与本系统完整备份 JSON；最大 10 MB</span>
          </label>
          {validation ? (
            <div className={`rounded-lg border p-3 text-sm ${validation.valid ? "border-emerald-600/20 bg-emerald-600/5" : "border-destructive/20 bg-destructive/5 text-destructive"}`}>
              {validation.message}
            </div>
          ) : null}
          {user?.isAdmin ? (
            <label className="field">
              <span>固定 IP（可选）</span>
              <SelectField
                value={proxyId}
                onValueChange={setProxyId}
                options={proxyOptions}
                placeholder="按当前 IP 策略自动分配"
                clearable
                disabled={pending}
              />
              <small>“仅手动分配”模式必须选择；其他模式留空会按策略自动选择。</small>
            </label>
          ) : null}
          {result ? (
            <div className="rounded-lg border border-emerald-600/20 bg-emerald-600/5 p-4">
              <div className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-400">
                <CheckCircle2Icon size={17} />导入请求已完成
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                账号：{field(result, "phoneNumber", "phone_number", "phone", "accountPublicId", "publicId") || "已入库"}
                {field(result, "status", "connectionStatus") ? ` · ${field(result, "status", "connectionStatus")}` : ""}
              </p>
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button disabled={!canManage || pending || !file || !validation?.valid}>
              {pending ? <LoaderCircleIcon className="spin" size={16} /> : <UploadCloudIcon size={16} />}
              校验并导入
            </Button>
          </div>
        </form>
        <aside className="card h-fit">
          <h3>导入规则</h3>
          <div className="mt-4 grid gap-4 text-sm text-muted-foreground">
            <p><strong className="text-foreground">统一协议：</strong>账号池统一使用 Baileys，不接受仅以“五段字符串”表示的不完整凭据。</p>
            <p><strong className="text-foreground">安全校验：</strong>系统会校验号码、身份密钥、设备签名与必要会话数据，不会把解析成功误判为连接成功。</p>
            <p><strong className="text-foreground">入池条件：</strong>恢复连接并完成基础资料同步后才可用于营销；资料未知期间显示“待同步”。</p>
          </div>
        </aside>
      </section>
    </StandardListPage>
  );
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
  const [exporting, setExporting] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await apiRequest("/api/personal-accounts?pageSize=100");
      setRows(unwrapList<unknown>(payload).rows.map(exportAccount));
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
    return search
      ? rows.filter((row) => `${row.phone} ${row.name} ${row.id}`.toLowerCase().includes(search))
      : rows;
  }, [keyword, rows]);

  async function download(row: ExportAccount, format: "baileys_creds" | "native") {
    const operation = `${row.id}:${format}`;
    setExporting(operation);
    try {
      const response = await apiDownload(`/api/personal-accounts/${row.id}/export?format=${format}`);
      const url = URL.createObjectURL(response.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = response.filename
        ? decodeURIComponent(response.filename)
        : `${row.phone || row.id}${format === "native" ? "-parloq-full" : ""}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("账号 JSON 已生成，请妥善保管凭据文件");
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "导出失败");
    } finally {
      setExporting("");
    }
  }

  return (
    <StandardListPage>
      <div className="rounded-lg border border-amber-600/20 bg-amber-600/5 px-4 py-3 text-sm">
        “兼容 JSON”可作为 Baileys creds 文件导入其他支持该凭据格式的环境；“完整备份”还包含 Signal key store，适合本系统间无损迁移。两种文件都属于敏感登录凭据，请勿通过公开渠道传输。
      </div>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索号码、名称或账号 ID" }}
        meta={`${visible.length} 个账号`}
        actions={<Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新</Button>}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载账号…</div> : visible.length ? (
          <Table>
            <TableHeader><TableRow><TableHead>账号</TableHead><TableHead>来源</TableHead><TableHead>连接状态</TableHead><TableHead>入库时间</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader>
            <TableBody>{visible.map((row) => (
              <TableRow key={row.id}>
                <TableCell><div className="cell-main"><strong>{row.name || row.phone || row.id}</strong><span>{row.phone || row.id}</span></div></TableCell>
                <TableCell>{sourceBadge(row.source)}</TableCell>
                <TableCell><Badge tone={row.connected ? "success" : "neutral"}>{row.connected ? "在线" : "离线"}</Badge></TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
                <TableCell><div className="flex justify-end gap-2">{row.connected ? <span className="self-center text-xs text-muted-foreground">请先断开</span> : null}<Button variant="outline" size="sm" disabled={!canManage || row.connected || Boolean(exporting)} onClick={() => void download(row, "baileys_creds")}>{exporting === `${row.id}:baileys_creds` ? <Spinner /> : <DownloadIcon size={15} />}兼容 JSON</Button><Button variant="outline" size="sm" disabled={!canManage || row.connected || Boolean(exporting)} onClick={() => void download(row, "native")}>{exporting === `${row.id}:native` ? <Spinner /> : <DownloadIcon size={15} />}完整备份</Button></div></TableCell>
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
  name: string;
  description: string;
  accountCount: number | null;
  createdAt: string;
};
function accountGroup(input: unknown): AccountGroup {
  const row = input as Record<string, unknown>;
  return {
    id: field(row, "publicId", "public_id", "id"),
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
  function edit(row?: AccountGroup) {
    setEditing(row || null);
    setName(row?.name || "");
    setDescription(row?.description || "");
    setOpen(true);
  }
  async function save() {
    if (!name.trim()) return;
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
    <StandardListPage>
      <ListToolbar
        search={{ value: keyword, onChange: setKeyword, placeholder: "搜索分组名称或说明" }}
        meta={`${visible.length} 个分组`}
        actions={<><Button variant="outline" onClick={() => void load()} disabled={loading}><RefreshCwIcon size={16} className={loading ? "spin" : ""} />刷新</Button>{canManage ? <Button onClick={() => edit()}><PlusIcon size={16} />新建分组</Button> : null}</>}
      />
      <ListTableCard>
        {loading ? <div className="loading-state"><Spinner />正在加载账号分组…</div> : visible.length ? (
          <Table><TableHeader><TableRow><TableHead>分组</TableHead><TableHead>账号数</TableHead><TableHead>创建时间</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader>
            <TableBody>{visible.map((row) => <TableRow key={row.id}>
              <TableCell><div className="cell-main"><strong>{row.name}</strong><span>{row.description || "暂无说明"}</span></div></TableCell>
              <TableCell>{row.accountCount == null ? <span className="text-muted-foreground">待同步</span> : row.accountCount}</TableCell>
              <TableCell className="text-muted-foreground">{formatDateTime(row.createdAt)}</TableCell>
              <TableCell><div className="flex justify-end gap-1">{canManage ? <><IconButton label="编辑分组" onClick={() => edit(row)}><PencilIcon size={15} /></IconButton><IconButton label="删除分组" className="text-destructive" onClick={() => void remove(row)}><Trash2Icon size={15} /></IconButton></> : null}</div></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        ) : <EmptyState title="还没有账号分组" description="创建分组后可按用途、国家或客户业务组织统一账号池。" />}
      </ListTableCard>
      <Drawer open={open} onClose={() => !pending && setOpen(false)} title={editing ? "编辑账号分组" : "新建账号分组"} description="分组仅用于组织和筛选，不改变账号凭据或连接状态。" footer={<><Button variant="outline" onClick={() => setOpen(false)}>取消</Button><Button disabled={pending || !name.trim()} onClick={() => void save()}>{pending ? <Spinner /> : null}保存</Button></>}>
        <div className="drawer-form"><label className="field"><span>分组名称</span><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：美国推广账号" /></label><label className="field"><span>分组说明（可选）</span><Textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="说明用途、地区或运营规则" /></label></div>
      </Drawer>
    </StandardListPage>
  );
}
